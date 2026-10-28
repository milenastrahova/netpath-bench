FROM alpine:3.21 AS build
RUN apk add --no-cache build-base cmake
WORKDIR /code
COPY CMakeLists.txt ./
COPY src ./src
RUN cmake -S . -B build -DCMAKE_BUILD_TYPE=Release && cmake --build build -j2
FROM alpine:3.21 AS runtime
# The build stage links against the GCC C++ runtime. The final Alpine image
# must carry the same shared runtime libraries (libstdc++.so.6/libgcc_s.so.1).
RUN apk add --no-cache libstdc++ libgcc \
    && addgroup -S bench && adduser -S bench -G bench \
    && mkdir /reports && chown bench:bench /reports
COPY --from=build /code/build/netpath-bench /usr/local/bin/netpath-bench
USER bench
# Regression gate: fail docker build before publishing an unrunnable binary.
RUN /usr/local/bin/netpath-bench selftest
ENTRYPOINT ["/usr/local/bin/netpath-bench"]
CMD ["selftest"]
