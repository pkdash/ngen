ARG UBUNTU_VERSION=22.04
FROM ubuntu:${UBUNTU_VERSION}

ENV DEBIAN_FRONTEND=noninteractive

# ---------------------------------------------------------------------------
# Base toolchain + the dependencies ngen's CI (.github/actions/ngen-build)
# installs for its default (no BMI_C / no Python / no MPI) build on
# ubuntu-22.04: NetCDF, UDUNITS2, and SQLite3 (for GeoPackage support).
# ---------------------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        gdb \
        cmake \
        git \
        curl \
        ca-certificates \
        tar \
        bzip2 \
        pkg-config \
        libnetcdf-dev \
        libnetcdf-c++4-1 \
        libnetcdf-c++4-dev \
        libudunits2-dev \
        libsqlite3-dev \
        python3 \
        python3-venv \
        python3-dev \
        python3-pip \
    && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
# Boost 1.79.0 — ngen's top-level CMakeLists.txt hard-requires this exact
# minimum version (find_package(Boost 1.79.0 REQUIRED)); Ubuntu 22.04's own
# libboost-dev package is only 1.74, so vendor the same tarball ngen's own
# CI/docker recipes (docker/CENTOS_TEST.dockerfile, .github/actions/ngen-build)
# use. Only headers are needed — ngen never links a compiled Boost component
# at the top level — so no b2/bootstrap build step is required.
# ---------------------------------------------------------------------------
ARG BOOST_VERSION=1.79.0
RUN cd /opt \
    && BOOST_ARCHIVE="boost_$(echo ${BOOST_VERSION} | tr '.' '_').tar.bz2" \
    && curl -fL -o "${BOOST_ARCHIVE}" "https://sourceforge.net/projects/boost/files/boost/${BOOST_VERSION}/${BOOST_ARCHIVE}/download" \
    && tar -xjf "${BOOST_ARCHIVE}" \
    && rm "${BOOST_ARCHIVE}"

ENV BOOST_ROOT=/opt/boost_1_79_0
