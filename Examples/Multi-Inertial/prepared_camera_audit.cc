#include "Frame.h"
#include "CameraModels/KannalaBrandt8.h"
#include "ORBextractor.h"
#include <opencv2/imgcodecs.hpp>
#include <fstream>
#include <iostream>
#include <memory>
#include <stdexcept>

// Uses the actual Frame constructor, including the optional domain gate and matching.
int main(int argc, char** argv) {
    try {
        if(argc!=3) throw std::runtime_error("Usage: prepared_camera_audit settings dataset");
        cv::FileStorage f(argv[1],cv::FileStorage::READ);
        std::vector<std::unique_ptr<ORB_SLAM3::KannalaBrandt8>> cameras;
        std::vector<std::unique_ptr<ORB_SLAM3::ORBextractor>> extractors;
        cv::Mat images[4];
        for(int c=0;c<4;++c) {
            std::vector<float> params;
            for(auto k:{"fx","fy","cx","cy","k1","k2","k3","k4"})
                params.push_back(float(f["Camera"+std::to_string(c+1)+"."+k]));
            cameras.emplace_back(new ORB_SLAM3::KannalaBrandt8(params));
            cameras.back()->mvLappingArea={0,1280};
            extractors.emplace_back(new ORB_SLAM3::ORBextractor(c<2?1000:2000,1.2,8,15,7));
            std::string base=std::string(argv[2])+"/mav0/cam"+std::to_string(c);
            std::ifstream csv(base+"/data.csv");std::string row;
            while(std::getline(csv,row)) if(!row.empty()&&row[0]!='#') break;
            auto name=row.substr(row.find(',')+1);if(!name.empty()&&name.back()=='\r')name.pop_back();
            images[c]=cv::imread(base+"/data/"+name,cv::IMREAD_GRAYSCALE);
            if(images[c].empty()) throw std::runtime_error("Unreadable camera "+std::to_string(c));
        }
        auto se3=[&](const char* key){cv::Mat m;f[key]>>m;return ORB_SLAM3::Converter::toSophus(m);};
        auto Tlr=se3("Stereo.T_c1_c2"),Tbc=se3("IMU.T_b_c1");
        auto Tlsl=Tbc.inverse()*se3("IMU.T_b_c3"),Tlsr=Tbc.inverse()*se3("IMU.T_b_c4");
        cv::Mat K=cameras[0]->toK(),dist=cv::Mat::zeros(4,1,CV_32F);
        ORB_SLAM3::IMU::Calib calib(Tbc,0,0,0,0);
        std::cout<<"filtered,camera,features,roundtrip_bad_over_2px,max_error_px,front_stereo_matches\n";
        for(bool filtered:{false,true}) {
            ORB_SLAM3::Frame frame(images[0],images[1],images[2],images[3],0,
                extractors[0].get(),extractors[1].get(),extractors[2].get(),extractors[3].get(),
                true,true,true,true,nullptr,K,dist,Tlr.translation().norm()*K.at<float>(0,0),40,
                cameras[0].get(),cameras[1].get(),cameras[2].get(),cameras[3].get(),
                Tlr,Tlsl,Tlsr,nullptr,calib,filtered);
            if(frame.mDescriptors.rows!=frame.N) throw std::runtime_error("Descriptor/keypoint alignment failed");
            int stereo=0;for(auto index:frame.mvLeftToRightMatch) {
                if(index>=frame.Nright) throw std::runtime_error("Stereo index out of bounds");
                stereo+=index>=0;
            }
            std::vector<cv::KeyPoint>* keys[]={&frame.mvKeys,&frame.mvKeysRight,&frame.mvKeysSideLeft,&frame.mvKeysSideRight};
            for(int c=0;c<4;++c) {
                int bad=0;double maximum=0;
                for(const auto& key:*keys[c]) {
                    auto q=cameras[c]->project(cameras[c]->unproject(key.pt));
                    double error=cv::norm(q-key.pt);
                    if(!std::isfinite(error)||error>2) ++bad;
                    if(std::isfinite(error)) maximum=std::max(maximum,error);
                }
                std::cout<<filtered<<','<<c<<','<<keys[c]->size()<<','<<bad<<','<<maximum<<','<<stereo<<'\n';
                if(filtered && bad) throw std::runtime_error("Invalid retained ray");
            }
        }
        return 0;
    } catch(const std::exception& e) {std::cerr<<e.what()<<'\n';return 1;}
}
