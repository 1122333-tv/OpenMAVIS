#include "Frame.h"
#include "ORBmatcher.h"
#include "ORBextractor.h"
#include "CameraModels/KannalaBrandt8.h"
#include "G2oTypes.h"
#include "Optimizer.h"
#include "System.h"
#include "Tracking.h"
#include "FrameDrawer.h"
#include "MapDrawer.h"
#include "KeyFrameDatabase.h"
#include <fstream>
#include <memory>
#include <iostream>
#include <stdexcept>

using namespace ORB_SLAM3;
static void check(bool valid,const char* text) {if(!valid) throw std::runtime_error(text);}
struct Fixture {
    std::vector<std::unique_ptr<KannalaBrandt8>> cameras;
    std::vector<std::unique_ptr<ORBextractor>> extractors;
    std::unique_ptr<Frame> frame;
    Map map{0};
    Fixture(bool rear=false) {
        cv::Mat image(480,640,CV_8U); cv::RNG rng(1234); rng.fill(image,cv::RNG::UNIFORM,0,256);
        for(int c=0;c<4;++c) {
            cameras.emplace_back(new KannalaBrandt8({c==1?550.f:c==2?260.f:c==3?280.f:400.f,400.f,c==1?180.f:320.f,240.f,0,0,0,0}));
            cameras.back()->mvLappingArea={0,640};
            extractors.emplace_back(new ORBextractor(100,1.2,2,15,7));
        }
        Sophus::SE3f right(Eigen::Matrix3f::Identity(),Eigen::Vector3f(.25f,0,0));
        if(rear) right=Sophus::SE3f(Eigen::AngleAxisf(M_PI/2,Eigen::Vector3f::UnitY()).toRotationMatrix(),Eigen::Vector3f(0,0,.3f));
        Sophus::SE3f leftSide(Eigen::AngleAxisf(-M_PI/2,Eigen::Vector3f::UnitY()).toRotationMatrix(),Eigen::Vector3f(-.1f,0,0));
        Sophus::SE3f rightSide(Eigen::AngleAxisf(M_PI/2,Eigen::Vector3f::UnitY()).toRotationMatrix(),Eigen::Vector3f(.1f,0,0));
        auto K=cameras[0]->toK();cv::Mat distortion=cv::Mat::zeros(4,1,CV_32F);
        frame.reset(new Frame(image,image,image,image,1,extractors[0].get(),extractors[1].get(),extractors[2].get(),extractors[3].get(),true,true,true,true,nullptr,K,distortion,100,40,cameras[0].get(),cameras[1].get(),cameras[2].get(),cameras[3].get(),right,leftSide,rightSide,nullptr,IMU::Calib(Sophus::SE3f(),0,0,0,0)));
        frame->SetImuPoseVelocity(Eigen::Matrix3f::Identity(),Eigen::Vector3f::Zero(),Eigen::Vector3f::Zero());
    }
    void keys(Frame& f,const Eigen::Vector3f& point,bool frontCandidate=true) {
        const Sophus::SE3f rel[]={Sophus::SE3f(),f.GetRelativePoseTrl(),f.GetRelativePoseTsll(),f.GetRelativePoseTsrl()};
        std::vector<cv::KeyPoint>* vectors[]={&f.mvKeys,&f.mvKeysRight,&f.mvKeysSideLeft,&f.mvKeysSideRight};
        f.Nleft=f.Nright=f.Nsideleft=f.Nsideright=1; f.N=4;
        f.mDescriptors=cv::Mat::zeros(4,32,CV_8U);f.mvpMapPoints.assign(4,nullptr);f.mvbOutlier.assign(4,false);
        for(int c=0;c<4;++c) {
            Eigen::Vector2f uv=cameras[c]->project(Eigen::Vector3f(rel[c]*point));
            if(c==0 && !frontCandidate) uv=Eigen::Vector2f(10,10);
            vectors[c]->assign(1,cv::KeyPoint(uv.x(),uv.y(),7,0,1,0));
            for(int x=0;x<FRAME_GRID_COLS;++x) for(int y=0;y<FRAME_GRID_ROWS;++y) {
                if(c==0) f.mGrid[x][y].clear();
                if(c==1) f.mGridRight[x][y].clear();
                if(c==2) f.mGridSideLeft[x][y].clear();
                if(c==3) f.mGridSideRight[x][y].clear();
            }
            int x=round((uv.x()-f.mnMinX)*f.mfGridElementWidthInv),y=round((uv.y()-f.mnMinY)*f.mfGridElementHeightInv);
            if(x>=0 && x<FRAME_GRID_COLS && y>=0 && y<FRAME_GRID_ROWS) {
                if(c==0) f.mGrid[x][y].push_back(0);
                if(c==1) f.mGridRight[x][y].push_back(0);
                if(c==2) f.mGridSideLeft[x][y].push_back(0);
                if(c==3) f.mGridSideRight[x][y].push_back(0);
            }
        }
    }
};
int main(int argc,char**argv) {
    int failed=0,total=0;
    auto test=[&](const char* name,auto fn) {++total;try{fn();std::cout<<"PASS "<<name<<'\n';}catch(const std::exception& e){++failed;std::cout<<"FAIL "<<name<<": "<<e.what()<<'\n';}};
    for(int scenario=0;scenario<5;++scenario) test(("projection_"+std::to_string(scenario)).c_str(),[&] {
        Fixture fixture;auto& current=*fixture.frame;
        const Eigen::Vector3f points[]={ {.4f,0,4},{-3,0,3},{3,0,3},{-4,0,.2f},{.4f,0,4} };
        fixture.keys(current,points[scenario],scenario!=4);
        Frame last(current);fixture.keys(last,points[scenario]);
        MapPoint point(points[scenario],&fixture.map,&last,0);point.nObs=1;last.mvpMapPoints[0]=&point;
        ORBmatcher matcher(.8,true);matcher.SearchByProjection(current,last,2,false);
        const int expected[]={1,2,3,2,1};
        check(current.mvpMapPoints[expected[scenario]]==&point,"own camera observation was suppressed or searched at wrong coordinates");
    });
    test("four_camera_pose_and_ray",[&] {
        Fixture fixture; auto& frame=*fixture.frame; const Eigen::Vector3f point(-3,.2,3);
        ImuCamPose pose(&frame);
        const Sophus::SE3f rel[]={Sophus::SE3f(),frame.GetRelativePoseTrl(),frame.GetRelativePoseTsll(),frame.GetRelativePoseTsrl()};
        for(int c=0;c<4;++c) {
            Eigen::Vector3f p=rel[c]*point;
            Eigen::Vector2f direct=fixture.cameras[c]->project(p);
            check((pose.Project(point.cast<double>(),c)-direct.cast<double>()).norm()<1e-3,"four camera optimizer pose disagrees with rig projection");
            if(p.z()>0) {
                const cv::Point2f pixel(direct.x(),direct.y());
                check(cv::norm(fixture.cameras[c]->project(fixture.cameras[c]->unproject(pixel))-pixel)<1e-3,"valid ray roundtrip failed");
            }
        }
    });
    test("triangulation_direction",[&] {
        Fixture fixture; Eigen::Vector3f point(.4,.2,3),triangulated;
        auto& frame=*fixture.frame;const auto T=frame.GetRelativePoseTlr();
        Eigen::Vector2f a=fixture.cameras[0]->project(point),b=fixture.cameras[1]->project(Eigen::Vector3f(T.inverse()*point));
        cv::KeyPoint ka(a.x(),a.y(),7),kb(b.x(),b.y(),7);
        float depth=fixture.cameras[0]->TriangulateMatches(fixture.cameras[1].get(),ka,kb,T.rotationMatrix(),T.translation(),1,1,triangulated);
        check(depth>0 && (triangulated-point).norm()<1e-3,"triangulation camera transform direction failed");
    });
#ifndef BASELINE_ABI
    test("four_camera_pose_optimization",[&] {
        Fixture fixture;auto& frame=*fixture.frame;const int count=8;
        frame.Nleft=frame.Nright=frame.Nsideleft=frame.Nsideright=count;frame.N=4*count;
        frame.mDescriptors=cv::Mat::zeros(frame.N,32,CV_8U);frame.mvpMapPoints.assign(frame.N,nullptr);frame.mvbOutlier.assign(frame.N,false);frame.mvuRight.assign(frame.N,-1);
        const Sophus::SE3f poses[]={Sophus::SE3f(),frame.GetRelativePoseTlr(),frame.GetRelativePoseTlsl(),frame.GetRelativePoseTlsr()};
        std::vector<cv::KeyPoint>* keys[]={&frame.mvKeys,&frame.mvKeysRight,&frame.mvKeysSideLeft,&frame.mvKeysSideRight};
        std::vector<std::unique_ptr<MapPoint>> points;
        for(int c=0;c<4;++c) {
            keys[c]->clear();
            for(int i=0;i<count;++i) {
                const Eigen::Vector3f pc((i%4-1.5f)*.3f,(i/4-.5f)*.4f,3+.2f*(i%3)),world=poses[c]*pc;
                const auto uv=fixture.cameras[c]->project(pc);keys[c]->emplace_back(uv.x(),uv.y(),7,0,1,0);
                points.emplace_back(new MapPoint(world,&fixture.map,&frame,c*count+i));points.back()->nObs=2;frame.mvpMapPoints[c*count+i]=points.back().get();
            }
        }
        frame.mvKeysUn=frame.mvKeys;
        frame.SetPose(Sophus::SE3f(Eigen::AngleAxisf(.01f,Eigen::Vector3f::UnitY()).toRotationMatrix(),Eigen::Vector3f(.02,-.01,.03)));
        const int inliers=Optimizer::PoseOptimization(&frame);
        check(inliers==frame.N && frame.GetPose().translation().norm()<1e-3 && frame.GetPose().so3().log().norm()<1e-3,"four-camera residual optimization did not recover the synthetic pose");
    });
    test("reset_frame_not_device_time_zero",[&] {
        Frame blank;check(!std::isfinite(blank.mTimeStamp) && blank.N==0,"reset frame incorrectly represents a timed exposure");
        Fixture fixture;check(std::isfinite(fixture.frame->mTimeStamp),"a real exposure has no valid time");
    });
    test("geometric_singleton_and_quality_gate",[&] {
        Fixture fixture;auto& frame=*fixture.frame;fixture.keys(frame,Eigen::Vector3f(.4,.2,3));
        frame.ComputeRigMatches({{0,1}});
        check(frame.rig_seeds.size()==1 && (frame.rig_seeds[0].point-Eigen::Vector3f(.4,.2,3)).norm()<1e-3,"singleton triangulation failed");
        check(frame.RigInitializationReady(1,1) && !frame.RigInitializationReady(2,1) && !frame.RigInitializationReady(1,4),"initialization count/coverage gate failed");
    });
    test("geometric_mutual_unique_right",[&] {
        Fixture fixture;auto& frame=*fixture.frame;fixture.keys(frame,Eigen::Vector3f(.4,.2,3));
        frame.mvKeys.push_back(frame.mvKeys[0]);frame.Nleft=2;frame.N=5;frame.mDescriptors=cv::Mat::zeros(5,32,CV_8U);
        frame.ComputeRigMatches({{0,1}});
        check(frame.rig_seeds.size()==1 && frame.rig_match_stats[0].mutual==1,"one right feature produced multiple points");
    });
    test("merge_shared_feature_seed",[&] {
        Fixture fixture;auto& frame=*fixture.frame;fixture.cameras[1]->setParameter(260,0);fixture.cameras[1]->setParameter(320,2);
        fixture.keys(frame,Eigen::Vector3f(-1.5,0,1.5));frame.ComputeRigMatches({{0,1},{0,2}});
        check(frame.rig_seeds.size()==1 && frame.rig_seeds[0].indices[0]==0 && frame.rig_seeds[0].indices[1]==1 && frame.rig_seeds[0].indices[2]==2,"shared features were counted as separate points");
    });
    test("side_seed_behind_cam0",[&] {
        Fixture fixture(true);auto& frame=*fixture.frame;fixture.keys(frame,Eigen::Vector3f(4,0,-.3));frame.ComputeRigMatches({{1,3}});
        check(frame.rig_seeds.size()==1 && frame.rig_seeds[0].point.z()<0 && frame.rig_seeds[0].indices[0]==-1,"valid side seed incorrectly requires positive cam0 depth");
    });
    test("preintegration_zero_single_constant_acceleration",[&] {
        IMU::Preintegrated pre(IMU::Bias(),IMU::Calib(Sophus::SE3f(),0,0,0,0));
        check(pre.dT==0,"zero-sample duration");
        const Eigen::Vector3f a(1.5,-.7,9.81);
        pre.IntegrateNewMeasurement(a,Eigen::Vector3f::Zero(),.001f);
        check(std::abs(pre.dT-.001)<1e-7,"single interval duration");
        for(int i=0;i<100;++i) pre.IntegrateNewMeasurement(a,Eigen::Vector3f::Zero(),.002f);
        const float t=.201f;
        const auto ev=(pre.GetUpdatedDeltaVelocity()-a*t).norm(),ep=(pre.GetUpdatedDeltaPosition()-a*(.5f*t*t)).norm();
        std::cout<<"analytic IMU error: dt="<<pre.dT-t<<" velocity="<<ev<<" position="<<ep<<'\n';
        check(std::abs(pre.dT-t)<1e-6 && ev<1e-5 && ep<1e-5,"constant acceleration integration differs from analytic motion");
    });
    test("preintegration_constant_angular_velocity",[&] {
        IMU::Preintegrated pre(IMU::Bias(),IMU::Calib(Sophus::SE3f(),0,0,0,0));
        for(int i=0;i<100;++i) pre.IntegrateNewMeasurement(Eigen::Vector3f::Zero(),Eigen::Vector3f(0,0,.2),.002f);
        const Eigen::Matrix3f expected=Eigen::AngleAxisf(.04f,Eigen::Vector3f::UnitZ()).toRotationMatrix();
        check((pre.GetUpdatedDeltaRotation()-expected).norm()<1e-5,"constant angular velocity integration failed");
    });
    for(float rate:{1e-6f,.2f,2.f}) test(("rotating_acceleration_"+std::to_string(rate)).c_str(),[&] {
        IMU::Preintegrated pre(IMU::Bias(),IMU::Calib(Sophus::SE3f(),0,0,0,0));
        for(int i=0;i<100;++i) pre.IntegrateNewMeasurement(Eigen::Vector3f(1,0,0),Eigen::Vector3f(0,0,rate),.002f);
        const double t=.2,x=rate*t;
        const Eigen::Vector3f velocity(std::sin(x)/rate,2*std::pow(std::sin(x/2),2)/rate,0);
        const Eigen::Vector3f position(2*std::pow(std::sin(x/2),2)/(rate*rate),(x-std::sin(x))/(rate*rate),0);
        check((pre.GetUpdatedDeltaVelocity()-velocity).norm()<2e-5 && (pre.GetUpdatedDeltaPosition()-position).norm()<2e-6,"rotating acceleration disagrees with closed form");
    });
#endif
    if(argc==1 || std::string(argv[1])!="--projection-only") {
        test("observation_idempotence",[&] {
            Fixture fixture;fixture.keys(*fixture.frame,Eigen::Vector3f(.4,0,4));
            KeyFrame kf(*fixture.frame,&fixture.map,nullptr);
            MapPoint point(Eigen::Vector3f(.4,0,4),&kf,&fixture.map);
            point.AddObservation(&kf,0);point.AddObservation(&kf,0);
            check(point.Observations()==1,"same observation counted twice");
        });
#ifndef BASELINE_ABI
        test("last_observation_erasure",[&] {
            Fixture fixture;fixture.keys(*fixture.frame,Eigen::Vector3f(.4,0,4));
            KeyFrame kf(*fixture.frame,&fixture.map,nullptr);
            MapPoint point(Eigen::Vector3f(.4,0,4),&kf,&fixture.map);
            kf.AddMapPoint(&point,0);point.AddObservation(&kf,0);point.EraseObservation(&kf);
            check(point.isBad() && point.Observations()==0 && point.GetReferenceKeyFrame()==nullptr,"last observation not removed safely");
        });
        test("merge_disjoint_camera_observations",[&] {
            Fixture fixture;fixture.keys(*fixture.frame,Eigen::Vector3f(-4,0,.2));
            KeyFrame kf(*fixture.frame,&fixture.map,nullptr);
            MapPoint a(Eigen::Vector3f(-4,0,.2),&kf,&fixture.map),b(Eigen::Vector3f(-4,0,.2),&kf,&fixture.map);
            a.AddObservation(&kf,2);kf.AddMapPoint(&a,2);b.AddObservation(&kf,0);kf.AddMapPoint(&b,0);
            a.Replace(&b);
            check(b.Observations()==2 && kf.GetMapPoint(2)==&b && kf.GetMapPoint(0)==&b,"fusion discarded a disjoint camera observation");
        });
        test("reference_camera_distance",[&] {
            Fixture fixture;fixture.keys(*fixture.frame,Eigen::Vector3f(-4,0,.2));
            KeyFrame kf(*fixture.frame,&fixture.map,nullptr);
            MapPoint point(Eigen::Vector3f(-4,0,.2),&kf,&fixture.map);point.AddObservation(&kf,2);point.UpdateNormalAndDepth();
            check(std::abs(point.GetMaxDistanceInvariance()-1.2f*(point.GetWorldPos()-kf.GetSideLeftCameraCenter()).norm())<1e-5,"distance uses a camera that did not observe the point");
        });
        for(int c=1;c<4;++c) test(("temporary_point_index_cam"+std::to_string(c)).c_str(),[&] {
            Fixture fixture;fixture.keys(*fixture.frame,Eigen::Vector3f(4,0,.2));
            fixture.frame->mvKeysRight.shrink_to_fit();fixture.frame->mvKeysSideLeft.shrink_to_fit();fixture.frame->mvKeysSideRight.shrink_to_fit();
            MapPoint point(Eigen::Vector3f(4,0,.2),&fixture.map,fixture.frame.get(),c);
            check(std::isfinite(point.GetMaxDistanceInvariance()),"invalid distance at camera global index");
        });
#endif
    }
#ifndef BASELINE_ABI
    if(argc==4 && std::string(argv[1])=="--empty-frame-diagnostics") test("inertial_bootstrap_rejects_unposed_keyframe",[&] {
        struct Probe:Tracking {using Tracking::Tracking;using Tracking::NeedNewKeyFrame;using Tracking::mpLastKeyFrame;};
        Settings settings(argv[3],System::IMU_MULTI);Atlas atlas(0);ORBVocabulary vocabulary;
        FrameDrawer drawer(&atlas,System::IMU_MULTI);MapDrawer mapDrawer(&atlas,argv[3],&settings);KeyFrameDatabase database(vocabulary);
        Probe tracking(nullptr,&vocabulary,&drawer,&mapDrawer,&atlas,&database,argv[3],System::IMU_MULTI,&settings);
        Fixture fixture;fixture.keys(*fixture.frame,Eigen::Vector3f(.4,0,4));KeyFrame kf(*fixture.frame,&fixture.map,nullptr);
        tracking.mpLastKeyFrame=&kf;tracking.mCurrentFrame.mTimeStamp=1.4;tracking.rig_bootstrap_require_ok=true;
        tracking.mState=Tracking::OK;
        check(!tracking.NeedNewKeyFrame(),"unposed frame entered inertial bootstrap");
        tracking.mCurrentFrame.SetPose(Sophus::SE3f());
        check(tracking.NeedNewKeyFrame(),"valid visual bootstrap keyframe rejected");
        tracking.mState=Tracking::RECENTLY_LOST;
        check(!tracking.NeedNewKeyFrame(),"recently lost frame entered inertial bootstrap");
        tracking.rig_bootstrap_require_ok=false;
        check(tracking.NeedNewKeyFrame(),"legacy control no longer reproduces permissive bootstrap");
        // An asynchronous initialization flag cannot make an unposed frame valid.
        Probe after(nullptr,&vocabulary,&drawer,&mapDrawer,&atlas,&database,argv[3],System::IMU_MULTI,&settings);
        atlas.SetImuInitialized();after.rig_bootstrap_require_ok=true;after.mState=Tracking::OK;
        check(!after.NeedNewKeyFrame(),"initialization flag admitted an unposed frame");
    });
    if(argc==4 && std::string(argv[1])=="--empty-frame-diagnostics") test("empty_frame_diagnostics",[&] {
        auto* slam=new System(argv[2],argv[3],System::IMU_MULTI,false);
        slam->EnableMultiDiagnostics(true);
        try {slam->SaveMultiDiagnostics(0);} catch(...) {slam->Shutdown();throw;}
        slam->Shutdown(); // upstream System owns process-lifetime worker threads
        std::ifstream events("diagnostic_events.csv");std::string header,event;
        std::getline(events,header);std::getline(events,event);
        check(event=="0,frame_cleared_at_map_boundary","cleared Frame diagnostic event missing");
    });
    test("online_body_transform_direction",[&] {
        Frame f;
        const Sophus::SE3f Tbc(Eigen::AngleAxisf(.3f,Eigen::Vector3f::UnitY()).toRotationMatrix(),Eigen::Vector3f(.2f,-.1f,.4f));
        const Sophus::SE3f Twb(Eigen::AngleAxisf(-.6f,Eigen::Vector3f::UnitZ()).toRotationMatrix(),Eigen::Vector3f(1,2,3));
        f.mImuCalib=IMU::Calib(Tbc,0,0,0,0);f.SetPose((Twb*Tbc).inverse());
        check((f.GetImuPose().matrix()-Twb.matrix()).norm()<1e-5,"online body pose direction wrong");
        check((f.GetPose().inverse()*f.mImuCalib.mTcb).matrix().isApprox(Twb.matrix(),1e-5),"snapshot differs from Frame body pose");
    });
    if(argc==4 && std::string(argv[1])=="--vio-mode") test("immutable_vio_lock_and_empty_pose",[&] {
        auto* slam=new System(argv[2],argv[3],System::IMU_MULTI,false);
        check(slam->IsVIOOnly(),"VIO mode not enabled");
        slam->ActivateLC();check(!slam->IsLoopClosingEnabled(),"GUI/API reactivated loop closure");
        const auto d=slam->GetMultiDiagnostics();
        check(!d.pose_valid && d.vio_only && !d.loop_enabled,"empty Frame or mode snapshot invalid");
        check(!d.loop_corrections && !d.merge_corrections && !d.loop_gba_runs,"VIO correction event observed");
        slam->Shutdown();
    });
#endif
    std::cout<<"RESULT "<<total-failed<<'/'<<total<<'\n';return failed?1:0;
}
