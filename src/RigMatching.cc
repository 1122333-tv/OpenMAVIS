#include "Frame.h"
#include "ORBmatcher.h"
#include "CameraModels/KannalaBrandt8.h"
#include <algorithm>
#include <limits>
#include <set>

namespace ORB_SLAM3 {
namespace {
struct Ray {
    Eigen::Vector3d v;
    Eigen::Matrix<double,3,2> jac;
};
Ray ray(GeometricCamera* camera,const cv::Point2f& pixel) {
    Ray r; r.v=camera->unprojectEig(pixel).cast<double>().normalized();
    // Central difference in pixels, before pyramid variance is applied.
    const float h=.5f;
    for(int d=0;d<2;++d) {
        cv::Point2f plus=pixel,minus=pixel;
        (d==0?plus.x:plus.y)+=h; (d==0?minus.x:minus.y)-=h;
        r.jac.col(d)=(camera->unprojectEig(plus).cast<double>().normalized()-camera->unprojectEig(minus).cast<double>().normalized())/(2*h);
    }
    return r;
}
}
void Frame::ComputeRigMatches(const std::vector<std::pair<int,int>>& pairs) {
    rig_matches_enabled=true;rig_seeds.clear();rig_match_stats.clear();rig_candidates.clear();
    const int offsets[]={0,Nleft,Nleft+Nright,Nleft+Nright+Nsideleft};
    const std::vector<cv::KeyPoint>* keys[]={&mvKeys,&mvKeysRight,&mvKeysSideLeft,&mvKeysSideRight};
    GeometricCamera* cameras[]={mpCamera,mpCamera2,mpCamera3,mpCamera4};
    const Sophus::SE3f poses[]={Sophus::SE3f(),GetRelativePoseTlr(),GetRelativePoseTlsl(),GetRelativePoseTlsr()};
    std::vector<Ray> rays[4];
    for(int c=0;c<4;++c) for(const auto& key:*keys[c]) rays[c].push_back(ray(cameras[c],key.pt));
    std::vector<RigSeed> candidates;
    for(const auto pair:pairs) {
        const int a=pair.first,b=pair.second;
        RigMatchStats stats;stats.a=a;stats.b=b;stats.queries=keys[a]->size();
        const Sophus::SE3f T=poses[a].inverse()*poses[b];
        const Eigen::Matrix3d E=Sophus::SO3d::hat(T.translation().cast<double>())*T.rotationMatrix().cast<double>();
        std::vector<Eigen::Vector3d> erb,etra;
        double maxJa=0,maxJb=0;
        for(const auto& r:rays[b]) {erb.push_back(E*r.v);maxJb=std::max(maxJb,r.jac.norm());}
        for(const auto& r:rays[a]) {etra.push_back(E.transpose()*r.v);maxJa=std::max(maxJa,r.jac.norm());}
        struct Best {int index=-1,d=257,second=257,count=0;};
        std::vector<Best> left(keys[a]->size()),right(keys[b]->size());
        for(size_t i=0;i<left.size();++i) for(size_t j=0;j<right.size();++j) {
            const double error=rays[a][i].v.dot(erb[j]);
            const double sa=mvLevelSigma2[(*keys[a])[i].octave],sb=mvLevelSigma2[(*keys[b])[j].octave];
            // Conservative upper variance bound rejects distant candidates cheaply.
            const double bound=sa*maxJa*maxJa*erb[j].squaredNorm()+sb*maxJb*maxJb*etra[i].squaredNorm();
            if(!std::isfinite(error) || !std::isfinite(bound) || error*error>3.841*bound) continue;
            const double variance=sa*(rays[a][i].jac.transpose()*erb[j]).squaredNorm()+sb*(rays[b][j].jac.transpose()*etra[i]).squaredNorm();
            if(variance<=1e-20 || !std::isfinite(variance) || error*error>3.841*variance) continue;
            const int distance=ORBmatcher::DescriptorDistance(mDescriptors.row(offsets[a]+i),mDescriptors.row(offsets[b]+j));
            auto update=[&](Best& best,int index) {
                ++best.count;
                if(distance<best.d) {best.second=best.d;best.d=distance;best.index=index;}
                else if(distance<best.second) best.second=distance;
            };
            update(left[i],j);update(right[j],i);
        }
        for(size_t i=0;i<left.size();++i) {
            const auto& best=left[i];
            if(best.index<0) {++stats.no_geometry;continue;}
            auto record=[&](int reason) {rig_candidates.push_back({a,b,offsets[a]+int(i),offsets[b]+best.index,reason,best.d});};
            if(best.count>1 && !(best.d<.8*best.second)) {++stats.ratio;record(1);continue;}
            if(best.d>ORBmatcher::TH_LOW) {++stats.hamming;record(2);continue;}
            if(right[best.index].index!=int(i)) {++stats.mutual;record(3);continue;}
            if(best.count==1) ++stats.singleton;
            Eigen::Vector3f point;
            const auto& ka=(*keys[a])[i];const auto& kb=(*keys[b])[best.index];
            const float depth=static_cast<KannalaBrandt8*>(cameras[a])->TriangulateMatches(cameras[b],ka,kb,T.rotationMatrix(),T.translation(),mvLevelSigma2[ka.octave],mvLevelSigma2[kb.octave],point);
            if(depth<=0 || !std::isfinite(depth) || !point.allFinite()) {
                const int code=std::isfinite(depth)?int(-depth)-1:-1;
                if(code>=0 && code<5) ++stats.geometry[code];else ++stats.invalid;
                record(code>=0 && code<5?4+code:9);
                continue;
            }
            if(depth<=.0001f) {++stats.invalid;record(9);continue;}
            RigSeed seed;seed.point=poses[a]*point;seed.indices[a]=offsets[a]+i;seed.indices[b]=offsets[b]+best.index;
            const Eigen::Vector3f pb=T.inverse()*point;
            seed.error=((cameras[a]->project(point)-Eigen::Vector2f(ka.pt.x,ka.pt.y)).squaredNorm()/mvLevelSigma2[ka.octave]+
                        (cameras[b]->project(pb)-Eigen::Vector2f(kb.pt.x,kb.pt.y)).squaredNorm()/mvLevelSigma2[kb.octave])/2;
            candidates.push_back(seed);++stats.accepted;record(0);
        }
        rig_match_stats.push_back(stats);
    }
    std::stable_sort(candidates.begin(),candidates.end(),[](const RigSeed& a,const RigSeed& b){return a.error<b.error;});
    std::vector<int> owners(N,-1);
    for(auto seed:candidates) {
        int shared=-1;bool conflict=false;
        for(int idx:seed.indices) if(idx>=0 && owners[idx]>=0) {
            if(shared>=0 && shared!=owners[idx]) conflict=true;
            shared=owners[idx];
        }
        if(conflict) continue;
        if(shared>=0) {
            auto combined=rig_seeds[shared].indices;
            for(int c=0;c<4;++c) if(seed.indices[c]>=0) {
                if(combined[c]>=0 && combined[c]!=seed.indices[c]) conflict=true;
                combined[c]=seed.indices[c];
            }
            for(int c=0;c<4 && !conflict;++c) if(combined[c]>=0) {
                const Eigen::Vector3f pc=poses[c].inverse()*rig_seeds[shared].point;
                const auto& key=(*keys[c])[combined[c]-offsets[c]];
                const Eigen::Vector2f uv=cameras[c]->project(pc);
                if(!pc.allFinite() || pc.z()<=0 || !uv.allFinite() || (uv-Eigen::Vector2f(key.pt.x,key.pt.y)).squaredNorm()>5.991*mvLevelSigma2[key.octave]) conflict=true;
            }
            if(conflict) continue;
            rig_seeds[shared].indices=combined;
        } else {shared=rig_seeds.size();rig_seeds.push_back(seed);}
        for(int idx:rig_seeds[shared].indices) if(idx>=0) owners[idx]=shared;
    }
    // Keep the legacy front stereo representation coherent for existing consumers.
    mvLeftToRightMatch.assign(Nleft,-1);mvRightToLeftMatch.assign(Nright,-1);
    mvDepth.assign(N,-1);mvuRight.assign(N,-1);mvStereo3Dpoints.resize(Nleft);
    for(const auto& seed:rig_seeds) if(seed.indices[0]>=0 && seed.indices[1]>=0) {
        const int left=seed.indices[0],right=seed.indices[1]-Nleft;
        mvLeftToRightMatch[left]=right;mvRightToLeftMatch[right]=left;mvStereo3Dpoints[left]=seed.point;mvDepth[left]=seed.point.z();
    }
}
bool Frame::RigInitializationReady(int minPoints,int minCells) const {
    std::vector<RigSeed> seeds=rig_seeds;
    if(!rig_matches_enabled) {
        std::set<int> right;
        for(int i=0;i<Nleft;++i) if(mvLeftToRightMatch[i]>=0 && right.insert(mvLeftToRightMatch[i]).second) {
            RigSeed seed;seed.indices[0]=i;seed.indices[1]=Nleft+mvLeftToRightMatch[i];seeds.push_back(seed);
        }
    }
    if(int(seeds.size())<minPoints) return false;
    const int offsets[]={0,Nleft,Nleft+Nright,Nleft+Nright+Nsideleft};
    const std::vector<cv::KeyPoint>* keys[]={&mvKeys,&mvKeysRight,&mvKeysSideLeft,&mvKeysSideRight};
    std::set<int> cells[4];
    for(const auto& seed:seeds) for(int c=0;c<4;++c) if(seed.indices[c]>=0) {
        const auto pixel=(*keys[c])[seed.indices[c]-offsets[c]].pt;
        const int x=int(4*(pixel.x-mnMinX)/(mnMaxX-mnMinX)),y=int(3*(pixel.y-mnMinY)/(mnMaxY-mnMinY));
        if(x>=0 && x<4 && y>=0 && y<3) cells[c].insert(y*4+x);
    }
    int cameras=0;for(int c=0;c<4;++c) cameras+=int(cells[c].size())>=minCells && !cells[c].empty();
    return cameras>=2;
}

}
