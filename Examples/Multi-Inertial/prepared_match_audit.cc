#include "Frame.h"
#include "CameraModels/KannalaBrandt8.h"
#include "ORBextractor.h"
#include <opencv2/imgcodecs.hpp>
#include <fstream>
#include <iostream>
#include <memory>
#include <set>
#include <array>
#include <stdexcept>

using namespace ORB_SLAM3;
using namespace std;
static vector<string> filenames(const string& base) {
    ifstream f(base+"/data.csv"); if(!f) throw runtime_error("Cannot read "+base);
    vector<string> names;string s;
    while(getline(f,s)) {if(s.empty()||s[0]=='#')continue;if(s.back()=='\r')s.pop_back();names.push_back(base+"/data/"+s.substr(s.find(',')+1));}
    if(names.empty()) throw runtime_error("Empty camera CSV");
    return names;
}
int main(int argc,char**argv) {
 try {
    if(argc!=4)throw runtime_error("Usage: prepared_match_audit settings dataset fresh_output.csv");
    if(ifstream(argv[3]).good())throw runtime_error("Output already exists");
    cv::FileStorage f(argv[1],cv::FileStorage::READ);ofstream out(argv[3]);if(!out)throw runtime_error("Cannot write output");
    out<<"frame,filtered,pair,ratio,left_features,right_features,queries,short_knn,ratio_reject,ratio_pass,parallax,left_depth,right_depth,left_reprojection,right_reprojection,nonfinite,tiny_depth,accepted,unique_right\n";
    vector<unique_ptr<KannalaBrandt8>> cams;vector<unique_ptr<ORBextractor>> extractors;array<vector<string>,4> names;
    for(int c=0;c<4;++c) {
        vector<float> params;for(auto k:{"fx","fy","cx","cy","k1","k2","k3","k4"})params.push_back(float(f["Camera"+to_string(c+1)+"."+k]));
        cams.emplace_back(new KannalaBrandt8(params));cams.back()->mvLappingArea={int(f["Camera"+to_string(c+1)+".overlappingBegin"]),int(f["Camera"+to_string(c+1)+".overlappingEnd"])};
        extractors.emplace_back(new ORBextractor(int(f["ORBextractor.nFeatures"])*(c<2?1:2),float(f["ORBextractor.scaleFactor"]),int(f["ORBextractor.nLevels"]),int(f["ORBextractor.iniThFAST"]),int(f["ORBextractor.minThFAST"])));
        names[c]=filenames(string(argv[2])+"/mav0/cam"+to_string(c));if(names[c].size()!=names[0].size())throw runtime_error("Camera count mismatch");
    }
    auto se3=[&](const char* k){cv::Mat m;f[k]>>m;return Converter::toSophus(m);};
    auto Tlr=se3("Stereo.T_c1_c2"),Tbc=se3("IMU.T_b_c1");auto Tlsl=Tbc.inverse()*se3("IMU.T_b_c3"),Tlsr=Tbc.inverse()*se3("IMU.T_b_c4");
    array<Sophus::SE3f,4> poses={Sophus::SE3f(),Tlr,Tlsl,Tlsr};
    auto K=cams[0]->toK();cv::Mat dist=cv::Mat::zeros(4,1,CV_32F);IMU::Calib calib(Tbc,0,0,0,0);cv::BFMatcher matcher(cv::NORM_HAMMING);
    for(size_t i=0;i<names[0].size();++i) {
        cv::Mat im[4];for(int c=0;c<4;++c){auto color=cv::imread(names[c][i],cv::IMREAD_COLOR);if(color.empty())throw runtime_error(names[c][i]);cv::cvtColor(color,im[c],cv::COLOR_BGR2GRAY);}
        for(bool filtered:{false,true}) {
            Frame frame(im[0],im[1],im[2],im[3],0,extractors[0].get(),extractors[1].get(),extractors[2].get(),extractors[3].get(),true,true,true,true,nullptr,K,dist,Tlr.translation().norm()*K.at<float>(0,0),40,cams[0].get(),cams[1].get(),cams[2].get(),cams[3].get(),Tlr,Tlsl,Tlsr,nullptr,calib,filtered);
            vector<cv::KeyPoint>* keys[]={&frame.mvKeys,&frame.mvKeysRight,&frame.mvKeysSideLeft,&frame.mvKeysSideRight};
            int sizes[]={frame.Nleft,frame.Nright,frame.Nsideleft,frame.Nsideright};int starts[]={0,sizes[0],sizes[0]+sizes[1],sizes[0]+sizes[1]+sizes[2]};
            for(int a=0;a<4;++a)for(int b=a+1;b<4;++b) {
                // Front pair: every frame. Other pairs: first 128 frames plus every 30th.
                if(!(a==0&&b==1) && !(i<128||i%30==0))continue;
                int ma=a==0&&b==1?frame.monoLeft:0,mb=a==0&&b==1?frame.monoRight:0;
                cv::Mat da=frame.mDescriptors.rowRange(starts[a]+ma,starts[a]+sizes[a]);cv::Mat db=frame.mDescriptors.rowRange(starts[b]+mb,starts[b]+sizes[b]);
                vector<vector<cv::DMatch>> matches;if(da.rows&&db.rows)matcher.knnMatch(da,db,matches,2);
                array<double,4> ratios={.7,.8,.9,.95};array<array<long,11>,4> counts{};array<set<int>,4> unique;
                auto T=poses[a].inverse()*poses[b];auto R=T.rotationMatrix();auto t=T.translation();
                for(const auto& m:matches) {
                    int reason=0;float depth=0;
                    if(m.size()>=2 && m[0].distance<m[1].distance*.95) {
                        auto& ka=(*keys[a])[m[0].queryIdx+ma];auto& kb=(*keys[b])[m[0].trainIdx+mb];Eigen::Vector3f point;
                        depth=cams[a]->TriangulateMatches(cams[b].get(),ka,kb,R,t,frame.mvLevelSigma2[ka.octave],frame.mvLevelSigma2[kb.octave],point);
                        if(!isfinite(depth))reason=8;else if(depth<0)reason=2+int(-depth);else if(depth<=.0001f)reason=9;else reason=10;
                    }
                    for(int q=0;q<4;++q) {
                        if(m.size()<2)++counts[q][0];
                        else if(!(m[0].distance<m[1].distance*ratios[q]))++counts[q][1];
                        else {++counts[q][2];++counts[q][reason];if(reason==10)unique[q].insert(m[0].trainIdx+mb);}
                    }
                }
                for(int q=0;q<4;++q) {
                    auto& n=counts[q];
                    out<<i<<','<<filtered<<','<<a<<b<<','<<ratios[q]<<','<<sizes[a]<<','<<sizes[b]<<','<<matches.size();
                    for(auto v:n)out<<','<<v;
                    out<<','<<unique[q].size()<<'\n';
                }
                if(a==0&&b==1) {
                    long actual=0;for(auto n:frame.mvLeftToRightMatch)actual+=n>=0;
                    if(actual!=counts[1][10])throw runtime_error("Audit mismatch with actual Frame matching");
                }
            }
        }
        if(i%100==0){out.flush();cerr<<"audited "<<i<<'/'<<names[0].size()<<'\n';}
    }
    return 0;
 }catch(const exception&e){cerr<<e.what()<<'\n';return 1;}
}
