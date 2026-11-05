#!/usr/bin/env bash
#
#  SPDX-License-Identifier: Apache-2.0
#
#  Copyright The original authors
#
#  Licensed under the Apache Software License version 2.0, available at http://www.apache.org/licenses/LICENSE-2.0
#

set -euo pipefail
cd "$(dirname "$0")/.."

export MAVEN_OPTS="${MAVEN_OPTS:---add-modules jdk.incubator.vector}"
common=(-B -T 1 -Pperformance-test
  -DforkCount=1 -DreuseForks=false
  "-Dperf.start=${PERF_START:-2023-01}" "-Dperf.end=${PERF_END:-2025-12}"
  "-Dperf.runs=${PERF_RUNS:-5}")
module=:hardwood-performance-testing-end-to-end

case "${1:-}" in
  prepare)
    echo 'BENCHMARK_PHASE preparation START protocol=e2e-build-separated-v2'
    # skipTests still compiles tests and runs generate-test-resources (fixtures).
    # -am installs every reactor dependency needed by the later standalone goal.
    # Microbenchmarks are not dependencies of end-to-end and are omitted.
    ./mvnw "${common[@]}" -pl "$module" -am install -DskipTests
    # Resolve the Surefire provider and its dynamically loaded dependencies too.
    # No such method exists: this initializes the provider without running a test.
    ./mvnw "${common[@]}" -pl "$module" surefire:test \
      '-Dtest=FlatPerformanceTest#__prepare_only__' -Dsurefire.failIfNoSpecifiedTests=false
    echo 'BENCHMARK_PHASE preparation END'
    ;;
  measure)
    echo "BENCHMARK_PROTOCOL e2e-build-separated-v2 product_revision=$(git rev-parse HEAD)"
    echo 'BENCHMARK_PHASE measurement START reactor_threads=1 forkCount=1 reuseForks=false'
    # No lifecycle phases, reactor expansion, network resolution or fixture work.
    # Keep arbitrary Surefire filters intact: commas can combine inclusions,
    # exclusions and regular expressions. Split only the two default methods.
    defaults='FlatPerformanceTest#comparePerformance,NestedPerformanceTest#comparePerformance'
    selectors=("${TESTS:-$defaults}")
    if [[ "${selectors[0]}" == "$defaults" ]]; then
      selectors=('FlatPerformanceTest#comparePerformance' 'NestedPerformanceTest#comparePerformance')
    fi
    for selector in "${selectors[@]}"; do
      echo "BENCHMARK_METHOD $selector START"
      ./mvnw "${common[@]}" -o -pl "$module" surefire:test "-Dtest=$selector"
      echo "BENCHMARK_METHOD $selector END"
    done
    echo 'BENCHMARK_PHASE measurement END'
    ;;
  *) echo "Usage: $0 {prepare|measure}" >&2; exit 2 ;;
esac
