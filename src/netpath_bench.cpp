// NetPath Bench: reproducible TCP/UDP echo RTT experiments; NOT hardware latency.
// C++17, Windows Winsock2 / Linux POSIX sockets. No privileged APIs.
#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <ctime>
#include <cmath>
#include <csignal>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <numeric>
#include <random>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

#ifdef _WIN32
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <winsock2.h>
#include <ws2tcpip.h>
#pragma comment(lib, "Ws2_32.lib")
using Socket = SOCKET;
static constexpr Socket invalid_socket = INVALID_SOCKET;
using SocketLen = int;
#else
#include <arpa/inet.h>
#include <netdb.h>
#include <netinet/in.h>
#include <sys/select.h>
#include <sys/socket.h>
#include <unistd.h>
using Socket = int;
static constexpr Socket invalid_socket = -1;
using SocketLen = socklen_t;
#endif

namespace {
constexpr uint32_t MAGIC = 0x47524e54; // GRNT
constexpr uint16_t VERSION = 1;
constexpr size_t HEADER = 28;
constexpr size_t MAX_FRAME = 8192;
std::atomic<bool> running{true};

void cleanup_socket(Socket s) {
    if (s != invalid_socket) {
#ifdef _WIN32
        closesocket(s);
#else
        close(s);
#endif
    }
}
class ManagedSocket {
public:
    explicit ManagedSocket(Socket v = invalid_socket) : s(v) {}
    ~ManagedSocket() { cleanup_socket(s); }
    ManagedSocket(const ManagedSocket&) = delete;
    ManagedSocket& operator=(const ManagedSocket&) = delete;
    Socket get() const { return s; }
    bool valid() const { return s != invalid_socket; }
private:
    Socket s;
};
struct SocketPlatform {
    SocketPlatform() {
#ifdef _WIN32
        WSADATA d{};
        if (WSAStartup(MAKEWORD(2, 2), &d) != 0) throw std::runtime_error("WSAStartup failed");
#endif
    }
    ~SocketPlatform() {
#ifdef _WIN32
        WSACleanup();
#endif
    }
};
void put16(uint8_t* p, uint16_t n) {
    p[0] = static_cast<uint8_t>(n >> 8); p[1] = static_cast<uint8_t>(n);
}
void put32(uint8_t* p, uint32_t n) {
    for (int i = 3; i >= 0; --i) { p[i] = static_cast<uint8_t>(n); n >>= 8; }
}
void put64(uint8_t* p, uint64_t n) {
    for (int i = 7; i >= 0; --i) { p[i] = static_cast<uint8_t>(n); n >>= 8; }
}
uint16_t get16(const uint8_t* p) { return static_cast<uint16_t>(static_cast<unsigned>(p[0]) << 8 | p[1]); }
uint32_t get32(const uint8_t* p) { uint32_t n=0; for(int i=0;i<4;++i) n=(n<<8)|p[i]; return n; }
uint64_t get64(const uint8_t* p) { uint64_t n=0; for(int i=0;i<8;++i) n=(n<<8)|p[i]; return n; }
struct Header { uint64_t session; uint32_t seq; uint32_t size; };
std::vector<uint8_t> make_frame(uint64_t session, uint32_t seq, size_t length) {
    if (length < HEADER || length > MAX_FRAME) throw std::invalid_argument("frame size out of range");
    std::vector<uint8_t> b(length, 0);
    put32(b.data(), MAGIC); put16(b.data()+4, VERSION); put16(b.data()+6, 0);
    put64(b.data()+8, session); put32(b.data()+16, seq);
    put32(b.data()+20, static_cast<uint32_t>(length)); put32(b.data()+24, 0);
    return b;
}
bool decode_header(const uint8_t* b, size_t len, Header& h) {
    if (len < HEADER || get32(b) != MAGIC || get16(b+4) != VERSION || get16(b+6) != 0 || get32(b+24) != 0) return false;
    h.session = get64(b+8); h.seq = get32(b+16); h.size = get32(b+20);
    return h.size >= HEADER && h.size <= MAX_FRAME;
}

int arg_int(int argc, char** argv, const std::string& key, int default_value, int min, int max) {
    for (int i=2;i<argc;++i) if (key == argv[i]) {
        if (i+1 >= argc) throw std::invalid_argument("value missing for " + key);
        std::string v=argv[i+1]; size_t used=0; long long x=0;
        try { x=std::stoll(v,&used); } catch(...) { throw std::invalid_argument("invalid integer " + key); }
        if (used!=v.size() || x<min || x>max) throw std::invalid_argument("out-of-range integer " + key);
        return static_cast<int>(x);
    }
    return default_value;
}
std::string arg_str(int argc, char** argv, const std::string& key, const std::string& fallback) {
    for(int i=2;i<argc;++i) if(key==argv[i]) {
        if(i+1>=argc) throw std::invalid_argument("missing value for " + key);
        return argv[i+1];
    }
    return fallback;
}
std::string escape_json(const std::string& s) {
    std::ostringstream out;
    for (unsigned char c: s) {
        if(c=='"'||c=='\\') out << '\\' << static_cast<char>(c);
        else if(c=='\n') out << "\\n";
        else if(c=='\r') out << "\\r";
        else if(c=='\t') out << "\\t";
        else if(c<32) {out << "\\u" << std::hex << std::setw(4) << std::setfill('0') << static_cast<int>(c) << std::dec;}
        else out << static_cast<char>(c);
    }
    return out.str();
}
Socket bind_socket(int port, int type, const std::string& bind_ip) {
    Socket s=socket(AF_INET,type,0);
    if(s==invalid_socket) throw std::runtime_error("socket() failed");
    int reuse=1;
    setsockopt(s,SOL_SOCKET,SO_REUSEADDR,reinterpret_cast<const char*>(&reuse),sizeof(reuse));
    sockaddr_in addr{}; addr.sin_family=AF_INET; addr.sin_port=htons(static_cast<uint16_t>(port));
    if (inet_pton(AF_INET, bind_ip.c_str(), &addr.sin_addr) != 1) {
        cleanup_socket(s); throw std::invalid_argument("invalid IPv4 bind address");
    }
    if(bind(s,reinterpret_cast<sockaddr*>(&addr),sizeof(addr)) != 0) {
        cleanup_socket(s); throw std::runtime_error("bind() failed: port busy or unavailable");
    }
    return s;
}
void bind_source(Socket s,const std::string& source_ip) {
    if(source_ip.empty()) return;
    sockaddr_in src{}; src.sin_family=AF_INET;src.sin_port=0;
    if(inet_pton(AF_INET, source_ip.c_str(), &src.sin_addr) != 1)
        throw std::invalid_argument("invalid IPv4 source address");
    if(bind(s,reinterpret_cast<sockaddr*>(&src),sizeof(src)) != 0)
        throw std::runtime_error("cannot bind source address; must exist in container namespace");
}
Socket connect_tcp(const std::string& host,int port,const std::string& source_ip) {
    addrinfo hints{}; hints.ai_family=AF_INET; hints.ai_socktype=SOCK_STREAM;
    addrinfo* result=nullptr;
    std::string service=std::to_string(port);
    if (getaddrinfo(host.c_str(),service.c_str(),&hints,&result)!=0) throw std::runtime_error("getaddrinfo failed for host");
    Socket found=invalid_socket;
    for(auto* p=result;p;p=p->ai_next) {
        Socket s=socket(p->ai_family, p->ai_socktype, p->ai_protocol);
        if(s==invalid_socket) continue;
        try { bind_source(s,source_ip); } catch(...) {cleanup_socket(s);freeaddrinfo(result);throw;}
        if(connect(s,p->ai_addr,static_cast<SocketLen>(p->ai_addrlen)) == 0) { found=s; break; }
        cleanup_socket(s);
    }
    freeaddrinfo(result);
    if(found==invalid_socket) throw std::runtime_error("TCP connect failed");
    return found;
}
struct Address { sockaddr_in address{}; };
Address resolve_udp(const std::string& host,int port) {
    addrinfo hints{};hints.ai_family=AF_INET;hints.ai_socktype=SOCK_DGRAM;
    addrinfo* result=nullptr;std::string service=std::to_string(port);
    if(getaddrinfo(host.c_str(),service.c_str(),&hints,&result)!=0) throw std::runtime_error("getaddrinfo failed");
    Address out{};std::memcpy(&out.address,result->ai_addr,sizeof(sockaddr_in));freeaddrinfo(result);return out;
}

bool wait_read(Socket s,int timeout_ms) {
    fd_set readers;FD_ZERO(&readers);FD_SET(s,&readers);
    timeval tv{timeout_ms/1000,static_cast<long>((timeout_ms%1000)*1000)};
    const int ready=select(static_cast<int>(s)+1,&readers,nullptr,nullptr,&tv);
    return ready>0 && FD_ISSET(s,&readers);
}
// Bounded receive; select called with remaining time for each chunk.
bool read_exact(Socket s,uint8_t* p,size_t n,int timeout_ms) {
    auto until=std::chrono::steady_clock::now()+std::chrono::milliseconds(timeout_ms);
    size_t received=0;
    while(received<n) {
        auto left=std::chrono::duration_cast<std::chrono::milliseconds>(until-std::chrono::steady_clock::now()).count();
        if(left<=0 || !wait_read(s,static_cast<int>(left))) return false;
        auto len=recv(s,reinterpret_cast<char*>(p+received),static_cast<int>(n-received),0);
        if(len<=0) return false;
        received += static_cast<size_t>(len);
    }
    return true;
}
bool write_exact(Socket s,const uint8_t* p,size_t n) {
    size_t sent=0;
    while(sent<n) {
        auto k=send(s,reinterpret_cast<const char*>(p+sent),static_cast<int>(n-sent),0);
        if(k<=0) return false;
        sent+=static_cast<size_t>(k);
    }
    return true;
}
void serve_tcp_client(Socket s) {
    ManagedSocket guard(s);
    std::array<uint8_t,HEADER> header{};
    while(running) {
        if(!read_exact(s,header.data(),HEADER,5000)) return;
        Header h{};
        if(!decode_header(header.data(),HEADER,h)) return;
        std::vector<uint8_t> data(h.size);
        std::copy(header.begin(),header.end(),data.begin());
        if(h.size>HEADER && !read_exact(s,data.data()+HEADER,h.size-HEADER,5000)) return;
        if(!write_exact(s,data.data(),data.size())) return;
    }
}
void signal_stop(int) {running=false;}
void serve(int port, const std::string& bind_ip) {
    ManagedSocket udp(bind_socket(port,SOCK_DGRAM,bind_ip));
    ManagedSocket tcp(bind_socket(port,SOCK_STREAM,bind_ip));
    if(listen(tcp.get(),16)!=0) throw std::runtime_error("listen failed");
    std::signal(SIGINT,signal_stop);
    std::signal(SIGTERM,signal_stop);
    std::cout << "READY bind=" << bind_ip << " port=" << port << std::endl;
    std::vector<uint8_t> buffer(MAX_FRAME);
    while(running) {
        fd_set readers; FD_ZERO(&readers); FD_SET(udp.get(),&readers); FD_SET(tcp.get(),&readers);
        timeval tv{0,200000};
        Socket highest=std::max(udp.get(),tcp.get());
        int ready=select(static_cast<int>(highest)+1,&readers,nullptr,nullptr,&tv);
        if(ready<=0) continue;
        if(FD_ISSET(udp.get(),&readers)) {
            sockaddr_in from{};SocketLen size=sizeof(from);
            auto got=recvfrom(udp.get(),reinterpret_cast<char*>(buffer.data()),static_cast<int>(buffer.size()),0,
                             reinterpret_cast<sockaddr*>(&from),&size);
            Header h{};
            if(got >= static_cast<int>(HEADER) && decode_header(buffer.data(),static_cast<size_t>(got),h) &&
               h.size==static_cast<uint32_t>(got)) {
                sendto(udp.get(),reinterpret_cast<const char*>(buffer.data()),got,0,
                       reinterpret_cast<sockaddr*>(&from),size);
            }
        }
        if(FD_ISSET(tcp.get(),&readers)) {
            sockaddr_in from{};SocketLen size=sizeof(from);
            Socket client=accept(tcp.get(),reinterpret_cast<sockaddr*>(&from),&size);
            if(client!=invalid_socket) std::thread(serve_tcp_client,client).detach();
        }
    }
}
using Steady = std::chrono::steady_clock;
struct ProbeSample {
    int seq=0;
    double start_offset_ms=0;
    double rtt_ms=std::numeric_limits<double>::quiet_NaN();
    std::string status;
};
struct Result {
    std::string protocol,host,source_ip,started_at_utc,ended_at_utc;
    int port=0,attempted=0,ok=0,timeouts=0,errors=0,unexpected=0,bytes=0;
    double duration_ms=0;
    std::vector<double> rtt_ms;
    std::vector<ProbeSample> samples;
};
std::string utc_now() {
    const auto now=std::chrono::system_clock::now();
    const std::time_t time=std::chrono::system_clock::to_time_t(now);
    std::tm utc{};
#ifdef _WIN32
    gmtime_s(&utc, &time);
#else
    gmtime_r(&time, &utc);
#endif
    std::ostringstream out;
    const auto millis=std::chrono::duration_cast<std::chrono::milliseconds>(now.time_since_epoch()).count()%1000;
    out<<std::put_time(&utc,"%Y-%m-%dT%H:%M:%S")<<"."<<std::setfill('0')<<std::setw(3)<<millis<<"Z";
    return out.str();
}
std::string number_or_null(double v);
std::string sample_csv(const Result& r) {
    std::ostringstream out;
    out<<"sequence,start_offset_ms,status,rtt_ms\n";
    for(const auto& sample:r.samples) {
        out<<sample.seq<<","<<number_or_null(sample.start_offset_ms)<<","<<sample.status<<","<<number_or_null(sample.rtt_ms)<<"\n";
    }
    return out.str();
}
double quantile(std::vector<double> values, double fraction) {
    if(values.empty()) return std::numeric_limits<double>::quiet_NaN();
    std::sort(values.begin(),values.end());
    size_t idx=std::max<size_t>(1,static_cast<size_t>(std::ceil(static_cast<double>(values.size())*fraction)))-1;
    return values[idx];
}
std::string number_or_null(double v) {
    if(!std::isfinite(v)) return "null";
    std::ostringstream s;s << std::fixed << std::setprecision(6) << v;return s.str();
}
std::string report(const Result& r) {
    double avg=std::numeric_limits<double>::quiet_NaN();
    if(!r.rtt_ms.empty()) avg=std::accumulate(r.rtt_ms.begin(),r.rtt_ms.end(),0.0)/static_cast<double>(r.rtt_ms.size());
    std::vector<double> variations;
    for(size_t i=1;i<r.rtt_ms.size();++i) variations.push_back(std::abs(r.rtt_ms[i]-r.rtt_ms[i-1]));
    std::ostringstream s;
    s << "{\n  \"schema_version\":1, \"experiment\":\"app_echo_rtt\", \"protocol\":\"" << r.protocol << "\",\n"
      << "  \"host\":\""<<escape_json(r.host)<<"\", \"source_ip\":\""<<escape_json(r.source_ip)<<"\", \"port\":"<<r.port<<", \"packet_bytes\":"<<r.bytes<<",\n"
      << "  \"attempted\":"<<r.attempted<<", \"successful_echoes\":"<<r.ok<<", \"timeouts\":"<<r.timeouts
      << ", \"errors\":"<<r.errors<<", \"unexpected_replies\":"<<r.unexpected<<",\n"
      << "  \"started_at_utc\":\""<<escape_json(r.started_at_utc)<<"\", \"ended_at_utc\":\""<<escape_json(r.ended_at_utc)<<"\", \"observation_duration_ms\":"<<number_or_null(r.duration_ms)<<",\n"
      << "  \"sample_count\":"<<r.samples.size()<<", \"time_series_format\":\"optional CSV with steady-clock offsets\",\n"
      << "  \"echo_failure_ratio\":"<<number_or_null(r.attempted==0?std::numeric_limits<double>::quiet_NaN():static_cast<double>(r.attempted-r.ok)/r.attempted)<<",\n"
      << "  \"rtt_ms\":{\"min\":"<<number_or_null(r.rtt_ms.empty()?std::numeric_limits<double>::quiet_NaN():*std::min_element(r.rtt_ms.begin(),r.rtt_ms.end()))
      << ",\"mean\":"<<number_or_null(avg)<<",\"p50\":"<<number_or_null(quantile(r.rtt_ms,0.50))
      << ",\"p95\":"<<number_or_null(quantile(r.rtt_ms,0.95))<<",\"p99\":"<<number_or_null(quantile(r.rtt_ms,0.99))
      << ",\"p999\":"<<number_or_null(quantile(r.rtt_ms,0.999))
      << ",\"max\":"<<number_or_null(quantile(r.rtt_ms,1.0))<<"},\n"
      << "  \"consecutive_abs_rtt_difference_ms\":{\"mean\":";
    if(variations.empty()) s << "null";
    else s << number_or_null(std::accumulate(variations.begin(),variations.end(),0.0)/static_cast<double>(variations.size()));
    s << ",\"p99\":"<<number_or_null(quantile(variations,0.99))<<"},\n"
      << "  \"limitations\":\"Sequential request/echo USERSPACE RTT in container or host. Timed-out UDP replies are missing acknowledgments, NOT confirmed network packet loss. Not one-way latency, NIC wire timestamping, PTP synchronized, DPDK or production network measurements. Percentiles use nearest-rank; sample-size affects tail confidence.\"\n}\n";
    return s.str();
}
Result client_udp(const std::string& host,int port,int count,int bytes,int interval_us,int timeout_ms,const std::string& source_ip,int duration_sec) {
    Address target=resolve_udp(host,port);
    ManagedSocket socket_handle(socket(AF_INET,SOCK_DGRAM,0));
    if(!socket_handle.valid()) throw std::runtime_error("UDP socket failure");
    bind_source(socket_handle.get(),source_ip);
    Result r{};r.protocol="udp";r.host=host;r.port=port;r.bytes=bytes;r.source_ip=source_ip;
    r.started_at_utc=utc_now(); const auto run_start=Steady::now();
    uint64_t session=static_cast<uint64_t>(std::random_device{}());
    session=(session<<32)^static_cast<uint64_t>(std::random_device{}());
    std::vector<uint8_t> answer(MAX_FRAME);
    for(int seq=0;seq<count;++seq) {
        if(duration_sec>0 && Steady::now()-run_start>=std::chrono::seconds(duration_sec)) break;
        auto frame=make_frame(session,static_cast<uint32_t>(seq),static_cast<size_t>(bytes));
        auto t0=Steady::now();
        ++r.attempted;
        ProbeSample sample{};sample.seq=seq;
        sample.start_offset_ms=std::chrono::duration<double,std::milli>(t0-run_start).count();
        auto size=sendto(socket_handle.get(),reinterpret_cast<const char*>(frame.data()),bytes,0,
                        reinterpret_cast<sockaddr*>(&target.address),sizeof(target.address));
        if(size!=bytes) {++r.errors;sample.status="send_error";r.samples.push_back(sample);continue;}
        bool matching=false;
        auto until=t0+std::chrono::milliseconds(timeout_ms);
        while(Steady::now()<until) {
            auto left=std::chrono::duration_cast<std::chrono::milliseconds>(until-Steady::now()).count();
            if(left<=0 || !wait_read(socket_handle.get(),static_cast<int>(left))) break;
            sockaddr_in from{};SocketLen from_size=sizeof(from);
            auto got=recvfrom(socket_handle.get(),reinterpret_cast<char*>(answer.data()),static_cast<int>(answer.size()),0,
                             reinterpret_cast<sockaddr*>(&from),&from_size);
            if(got<static_cast<int>(HEADER)) {++r.unexpected;continue;}
            Header h{};
            if(!decode_header(answer.data(),static_cast<size_t>(got),h) || h.session!=session || h.seq!=static_cast<uint32_t>(seq) || h.size!=static_cast<uint32_t>(got) ||
               from.sin_addr.s_addr!=target.address.sin_addr.s_addr || from.sin_port!=target.address.sin_port) {
                ++r.unexpected;continue;
            }
            auto t1=Steady::now();
            sample.rtt_ms=std::chrono::duration<double,std::milli>(t1-t0).count();
            r.rtt_ms.push_back(sample.rtt_ms);
            ++r.ok;matching=true;break;
        }
        if(!matching) ++r.timeouts;
        sample.status=matching?"ok":"timeout";
        r.samples.push_back(sample);
        if(interval_us>0) std::this_thread::sleep_for(std::chrono::microseconds(interval_us));
    }
    r.duration_ms=std::chrono::duration<double,std::milli>(Steady::now()-run_start).count();
    r.ended_at_utc=utc_now();
    return r;
}
Result client_tcp(const std::string& host,int port,int count,int bytes,int interval_us,int timeout_ms,const std::string& source_ip,int duration_sec) {
    ManagedSocket conn(connect_tcp(host,port,source_ip));
    Result r{};r.protocol="tcp";r.host=host;r.port=port;r.bytes=bytes;r.source_ip=source_ip;
    r.started_at_utc=utc_now(); const auto run_start=Steady::now();
    uint64_t session=static_cast<uint64_t>(std::random_device{}());
    std::vector<uint8_t> reply(static_cast<size_t>(bytes));
    for(int seq=0;seq<count;++seq) {
        if(duration_sec>0 && Steady::now()-run_start>=std::chrono::seconds(duration_sec)) break;
        auto data=make_frame(session,static_cast<uint32_t>(seq),static_cast<size_t>(bytes));
        auto t0=Steady::now();
        ++r.attempted;
        ProbeSample sample{};sample.seq=seq;
        sample.start_offset_ms=std::chrono::duration<double,std::milli>(t0-run_start).count();
        if(!write_exact(conn.get(),data.data(),data.size())) {++r.errors;sample.status="send_error";r.samples.push_back(sample);break;}
        if(!read_exact(conn.get(),reply.data(),reply.size(),timeout_ms)) {++r.timeouts;sample.status="timeout";r.samples.push_back(sample);break;}
        Header h{};
        if(!decode_header(reply.data(),reply.size(),h) || h.seq!=static_cast<uint32_t>(seq) || h.session!=session ||
           h.size!=static_cast<uint32_t>(bytes)) {++r.unexpected;sample.status="invalid_echo";r.samples.push_back(sample);break;}
        auto t1=Steady::now();
        sample.rtt_ms=std::chrono::duration<double,std::milli>(t1-t0).count();
        sample.status="ok";r.samples.push_back(sample);
        r.rtt_ms.push_back(sample.rtt_ms);
        ++r.ok;
        if(interval_us>0) std::this_thread::sleep_for(std::chrono::microseconds(interval_us));
    }
    r.duration_ms=std::chrono::duration<double,std::milli>(Steady::now()-run_start).count();
    r.ended_at_utc=utc_now();
    return r;
}
void selftest() {
    for (size_t length : {HEADER, size_t{64}, size_t{1200}, MAX_FRAME}) {
        auto data=make_frame(0x1234567890abcdefULL, 0xabcdef98U, length);
        Header h{};
        if(!decode_header(data.data(),data.size(),h) || h.session!=0x1234567890abcdefULL || h.seq!=0xabcdef98U || h.size!=length)
            throw std::runtime_error("frame roundtrip failed");
        data[0]=0;
        if(decode_header(data.data(),data.size(),h)) throw std::runtime_error("bad magic accepted");
    }
    if(std::abs(quantile({1,2,3,4,5},0.95)-5)>1e-9) throw std::runtime_error("percentile error");
    Result empty{};
    if(report(empty).find("\"p99\":null")==std::string::npos) throw std::runtime_error("null percentiles missing");
    Result sample_run{};sample_run.samples.push_back(ProbeSample{5,2.0,1.5,"ok"});
    sample_run.samples.push_back(ProbeSample{6,5.0,std::numeric_limits<double>::quiet_NaN(),"timeout"});
    if(sample_csv(sample_run).find("6,5.000000,timeout,null") == std::string::npos)
        throw std::runtime_error("CSV sample encoding failed");
    std::cout << "SELFTEST PASS: codec, invalid magic, quantile, null stats, CSV samples\n";
}
void usage() {
    std::cout << "NetPath Bench v0.2.1\n"
              << "  netpath-bench serve --port 9000 [--bind 0.0.0.0]\n"
              << "  netpath-bench udp --host server --port 9000 --count 200 --bytes 64 --timeout-ms 300 --interval-us 1000 --json /reports/udp.json --csv /reports/udp.csv [--source-ip 10.10.10.1] [--duration-sec 30]\n"
              << "  netpath-bench tcp --host server --port 9000 --count 200 --bytes 64 --timeout-ms 300 --interval-us 1000 --json /reports/tcp.json --csv /reports/tcp.csv [--source-ip 10.10.10.1] [--duration-sec 30]\n"
              << "  netpath-bench selftest\n";
}
} // namespace

int main(int argc,char** argv) {
    try {
        SocketPlatform sockets;
        if(argc<2) {usage();return 1;}
        std::string mode=argv[1];
        if(mode=="--help" || mode=="help") {usage();return 0;}
        if(mode=="selftest") {selftest();return 0;}
        int port=arg_int(argc,argv,"--port",9000,1024,65535);
        if(mode=="serve") {serve(port,arg_str(argc,argv,"--bind","0.0.0.0"));return 0;}
        if(mode!="tcp" && mode!="udp") {usage();return 1;}
        const std::string host=arg_str(argc,argv,"--host","127.0.0.1");
        const int duration_sec=arg_int(argc,argv,"--duration-sec",0,0,1800);
        const int count=arg_int(argc,argv,"--count",duration_sec>0?100000:200,1,100000);
        const std::string source_ip=arg_str(argc,argv,"--source-ip","");
        const int bytes=arg_int(argc,argv,"--bytes",64,static_cast<int>(HEADER),mode=="udp"?1400:static_cast<int>(MAX_FRAME));
        const int timeout_ms=arg_int(argc,argv,"--timeout-ms",300,1,60000);
        const int interval_us=arg_int(argc,argv,"--interval-us",1000,0,10000000);
        Result result=(mode=="udp")?client_udp(host,port,count,bytes,interval_us,timeout_ms,source_ip,duration_sec):client_tcp(host,port,count,bytes,interval_us,timeout_ms,source_ip,duration_sec);
        std::string json=report(result);
        std::cout << json;
        const std::string csv_path=arg_str(argc,argv,"--csv","");
        if(!csv_path.empty()) {
            std::ofstream csv(csv_path,std::ios::binary);
            if(!csv) throw std::runtime_error("cannot open output CSV file");
            csv<<sample_csv(result);
            if(!csv) throw std::runtime_error("cannot write output CSV file");
        }
        std::string destination=arg_str(argc,argv,"--json","");
        if(!destination.empty()) {
            std::ofstream file(destination,std::ios::binary);
            if(!file) throw std::runtime_error("cannot open output JSON file");
            file << json;
            if(!file) throw std::runtime_error("cannot write output JSON file");
        }
        return result.ok==result.attempted && result.unexpected==0 && result.attempted>0 ? 0:2;
    } catch(const std::exception& e) {
        std::cerr << "ERROR: " << e.what() << "\n";
        return 1;
    }
}
