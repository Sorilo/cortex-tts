FROM ubuntu:24.04 AS build
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates git cmake ninja-build build-essential glslc glslang-tools \
    spirv-headers spirv-tools libvulkan-dev python3 \
    && rm -rf /var/lib/apt/lists/*
ARG BREEZE_REF=8622f794bfe81649246ff908c8ca9247d9438556
RUN git clone https://github.com/HoppouAI/Breeze-TTS-2.cpp.git /src \
    && cd /src && git checkout "$BREEZE_REF" && git submodule update --init --recursive
RUN cmake -S /src -B /build -G Ninja -DCMAKE_BUILD_TYPE=Release \
    -DBREEZE_VULKAN=ON -DBREEZE_BUILD_CLI=OFF -DBREEZE_BUILD_SHARED=OFF \
    && cmake --build /build --target breeze-server -j 4

FROM ubuntu:24.04
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates libvulkan1 libgomp1 && rm -rf /var/lib/apt/lists/*
COPY --from=build /build/breeze-server /usr/local/bin/breeze-server
COPY --from=build /build/third_party/ggml/src/libggml*.so* /usr/local/lib/
COPY --from=build /build/third_party/ggml/src/ggml-vulkan/libggml-vulkan.so* /usr/local/lib/
RUN ldconfig
ENV NVIDIA_VISIBLE_DEVICES=all \
    NVIDIA_DRIVER_CAPABILITIES=compute,utility,graphics,display
EXPOSE 8080 8081
ENTRYPOINT ["/usr/local/bin/breeze-server"]
CMD ["/models/breeze-tts-2-q4_k.gguf", "--host", "0.0.0.0", "--port", "8080", "--ws-port", "8081", "--voices-dir", "/voices", "--chunk-first", "4", "--chunk-max", "25"]
