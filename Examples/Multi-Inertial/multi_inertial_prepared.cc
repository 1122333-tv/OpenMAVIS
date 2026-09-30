#include "System.h"
#include <opencv2/imgcodecs.hpp>
#include <array>
#include <chrono>
#include <cmath>
#include <fstream>
#include <iomanip>
#include <limits>
#include <map>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <sys/stat.h>
#include <thread>
#include <unistd.h>

using namespace std;
using Clock = chrono::steady_clock;
struct ImageRow { int64_t ns; string path; };
struct ImuRow { int64_t ns; array<float,6> v; };
static void require(bool ok, const string& message) { if(!ok) throw runtime_error(message); }
static int64_t integer(const string& s) {
    size_t n; auto v=stoll(s,&n); require(n==s.size(),"Invalid integer: "+s); return v;
}
static string absolute(const string& s) {
    char* r=realpath(s.c_str(),nullptr); require(r,"Cannot resolve path: "+s);
    string result(r); free(r); return result;
}
static vector<vector<string>> csv(const string& path) {
    ifstream f(path); require(bool(f),"Cannot open CSV: "+path);
    vector<vector<string>> rows; string s;
    while(getline(f,s)) {
        if(!s.empty() && s.back()=='\r') s.pop_back();
        if(s.empty() || s[0]=='#') continue;
        vector<string> row; string cell; stringstream ss(s);
        while(getline(ss,cell,',')) row.push_back(cell);
        rows.push_back(row);
    }
    require(!rows.empty(),"Empty CSV: "+path); return rows;
}
static int64_t shifted(int64_t t, int64_t offset) {
    require(!((offset>0 && t>numeric_limits<int64_t>::max()-offset) ||
              (offset<0 && t<numeric_limits<int64_t>::min()-offset)),"Timestamp overflow");
    return t+offset;
}
int main(int argc,char**argv) {
    unique_ptr<ORB_SLAM3::System> slam;
    try {
        map<string,string> opts; bool viewer=false,realtime=false,validate=false,diagnostics=false;
        for(int i=1;i<argc;++i) {
            string k=argv[i];
            if(k=="--viewer") viewer=true;
            else if(k=="--realtime") realtime=true;
            else if(k=="--validate-only") validate=true;
            else if(k=="--diagnostics") diagnostics=true;
            else {
                require(k=="--vocabulary" || k=="--settings" || k=="--dataset" || k=="--output" || k=="--cam-time-offset-ns" || k=="--max-frames","Unknown option: "+k);
                require(i+1<argc,"Missing value for "+k); require(!opts.count(k),"Duplicate option: "+k); opts[k]=argv[++i];
            }
        }
        for(auto k:{"--vocabulary","--settings","--dataset","--output","--cam-time-offset-ns"}) require(opts.count(k),string("Required option: ")+k);
        string dataset=absolute(opts["--dataset"]),settings=absolute(opts["--settings"]),vocab=absolute(opts["--vocabulary"]);
        int64_t offset=integer(opts["--cam-time-offset-ns"]);
        cv::FileStorage fs(settings,cv::FileStorage::READ); require(fs.isOpened(),"Cannot read settings");
        require(fs["Camera.fps"].isInt(),"Camera.fps must be integer");
        int width=int(fs["Camera.width"]),height=int(fs["Camera.height"]);
        require(width>0 && height>0,"Invalid image dimensions");
        array<vector<ImageRow>,4> images;
        for(int c=0;c<4;++c) {
            string base=dataset+"/mav0/cam"+to_string(c);
            for(const auto& row:csv(base+"/data.csv")) {
                require(row.size()==2,"Expected timestamp,filename in cam"+to_string(c));
                int64_t t=integer(row[0]);
                require(images[c].empty() || t>images[c].back().ns,"Non-monotonic timestamp cam"+to_string(c));
                string path=base+"/data/"+row[1]; ifstream f(path);
                require(bool(f),"Missing image cam"+to_string(c)+" frame "+to_string(images[c].size())+": "+path);
                images[c].push_back({t,path});
            }
            require(images[c].size()==images[0].size(),"Camera row count mismatch");
            for(size_t i=0;i<images[c].size();++i) require(images[c][i].ns==images[0][i].ns,"Camera timestamp mismatch cam"+to_string(c)+" frame "+to_string(i));
        }
        vector<ImuRow> imu;
        for(const auto& row:csv(dataset+"/mav0/imu0/data.csv")) {
            require(row.size()==7,"Expected seven IMU columns"); ImuRow r; r.ns=integer(row[0]);
            require(imu.empty() || r.ns>imu.back().ns,"Non-monotonic IMU timestamp");
            for(int j=0;j<6;++j) { size_t n; r.v[j]=stof(row[j+1],&n); require(n==row[j+1].size() && isfinite(r.v[j]),"Invalid IMU value"); }
            imu.push_back(r);
        }
        size_t count=images[0].size();
        if(opts.count("--max-frames")) { auto n=integer(opts["--max-frames"]); require(n>0,"max-frames must be positive"); count=min(count,size_t(n)); }
        require(imu.front().ns<shifted(images[0].front().ns,offset) && imu.back().ns>shifted(images[0].back().ns,offset),"IMU does not cover corrected camera timestamps");
        require(mkdir(opts["--output"].c_str(),0755)==0,"Output must be a fresh directory with existing parent: "+opts["--output"]);
        string output=absolute(opts["--output"]); require(chdir(output.c_str())==0,"Cannot enter output directory");
        ofstream meta("input_summary.json"); meta<<"{\"input_frames\":"<<images[0].size()<<",\"requested_frames\":"<<count<<",\"imu_samples\":"<<imu.size()<<",\"cam_time_offset_ns\":"<<offset<<"}\n";meta.close();
        auto decode=[&](size_t i) {
            array<cv::Mat,4> im;
            for(int c=0;c<4;++c) {
                im[c]=cv::imread(images[c][i].path,cv::IMREAD_COLOR);
                require(!im[c].empty() && im[c].cols==width && im[c].rows==height,"Invalid image cam"+to_string(c)+" frame "+to_string(i)+": "+images[c][i].path);
            } return im;
        };
        if(validate) { for(size_t i=0;i<count;++i) decode(i); cout<<"VALIDATED "<<count<<" groups, "<<imu.size()<<" IMU samples\n"; return 0; }
        slam.reset(new ORB_SLAM3::System(vocab,settings,ORB_SLAM3::System::IMU_MULTI,viewer));
        slam->EnableMultiDiagnostics(diagnostics);
        ofstream detail;
        if(diagnostics) {
            require(mkdir("overlays",0755)==0,"Cannot create diagnostic overlay directory");
            detail.open("diagnostics.csv"); detail<<"frame,time,state,unique_inliers,preintegration_dt";
            for(const auto* group:{"motion_visible","motion_candidates","motion_matches","reference_matches","local_visible","local_candidates","local_before","local_after","residual_before","residual_after"})
                for(int c=0;c<4;++c) detail<<','<<group<<"_cam"<<c;
            detail<<",rig_seeds,motion_success,reference_success,local_success"<<endl;
        }
        ofstream frames("frames.csv"); frames<<"frame,raw_ns,corrected_ns,imu_count,imu_first_ns,imu_last_ns,state,cam0_features,cam1_features,cam2_features,cam3_features,imu_initialized,map_id,maps,resets,stereo_matches,inliers,track_ms\n";
        size_t cursor=0; int64_t start=shifted(images[0][0].ns,offset);
        // Keep the last sample before the first exposure. Thereafter submit each sample
        // once, including one sample at/after the frame boundary for interpolation.
        while(cursor+1<imu.size() && imu[cursor+1].ns<start) ++cursor;
        bool any_ok=false;
        for(size_t i=0;i<count;++i) {
            auto im=decode(i); int64_t t=shifted(images[0][i].ns,offset); vector<ORB_SLAM3::IMU::Point> samples;
            size_t begin=cursor;
            while(cursor<imu.size()) {
                const auto&r=imu[cursor++];samples.emplace_back(r.v[3],r.v[4],r.v[5],r.v[0],r.v[1],r.v[2],r.ns*1e-9);
                if(r.ns>=t) break;
            }
            require(!samples.empty(),"No IMU samples for frame "+to_string(i));
            auto before=Clock::now(); slam->TrackMulti(im[0],im[1],im[2],im[3],t*1e-9,samples);
            double ms=chrono::duration<double,milli>(Clock::now()-before).count();auto d=slam->GetMultiDiagnostics();any_ok|=d.state==2;
            frames<<i<<','<<images[0][i].ns<<','<<t<<','<<samples.size()<<','<<imu[begin].ns<<','<<imu[cursor-1].ns<<','<<d.state;
            for(auto n:d.features) frames<<','<<n;
            frames<<','<<d.imu_initialized<<','<<d.map_id<<','<<d.maps<<','<<d.resets<<','<<d.stereo_matches<<','<<d.inliers<<','<<ms<<endl;
            if(diagnostics) {
                detail<<setprecision(17)<<i<<','<<t*1e-9<<','<<d.state<<','<<d.unique_inliers<<','<<d.preintegration_dt;
                for(auto group:{d.motion_visible,d.motion_candidates,d.motion_matches,d.reference_matches,d.local_visible,d.local_candidates,d.local_before,d.local_after})
                    for(int c=0;c<4;++c) detail<<','<<group[c];
                for(auto group:{d.residual_before,d.residual_after}) for(int c=0;c<4;++c) detail<<','<<group[c];
                detail<<','<<d.rig_seeds;for(int success:d.stage_success) detail<<','<<success;detail<<endl;
                slam->SaveMultiDiagnostics(i);
            }
            if(i%50==0) cout<<"PREPARED frame="<<i<<" state="<<d.state<<" imu_initialized="<<d.imu_initialized<<" map="<<d.map_id<<endl;
            if(realtime && i+1<count) { double remaining=(images[0][i+1].ns-images[0][i].ns)*1e-9-ms/1000; if(remaining>0) this_thread::sleep_for(chrono::duration<double>(remaining)); }
        }
        slam->Shutdown();
        if(any_ok) { slam->SaveTrajectoryEuRoC("trajectory_body.txt");slam->SaveKeyFrameTrajectoryEuRoC("keyframes_body.txt"); }
        slam.release(); // upstream System has process-lifetime thread ownership
        return 0;
    } catch(const exception&e) {
        cerr<<"PREPARED ERROR: "<<e.what()<<endl;
        if(slam) { slam->Shutdown(); slam.release(); }
        return 1;
    }
}
