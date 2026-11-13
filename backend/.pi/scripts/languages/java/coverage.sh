#!/usr/bin/env bash
# ============================================================================
# coverage.sh — Java: real line coverage via JaCoCo (maven/gradle)
#
# Runs tests and the JaCoCo report, then parses the TOTAL line-coverage
# percentage from the generated HTML report.
#
# Usage (normally via the .pi/scripts/coverage.sh dispatcher):
#   bash coverage.sh            # measure coverage
#   bash coverage.sh --gate     # fail if lines < COVERAGE_THRESHOLD
#   bash coverage.sh --lcov     # keep the jacoco.xml report artifact
#
# Env:
#   COVERAGE_THRESHOLD  minimum line-coverage % (default: 60)
# ============================================================================
set -uo pipefail

COVERAGE_THRESHOLD="${COVERAGE_THRESHOLD:-60}"
GATE=0
LCOV=0

for arg in "$@"; do
    case "$arg" in
        --gate) GATE=1 ;;
        --lcov) LCOV=1 ;;
        *) echo "unknown arg: $arg" >&2; exit 2 ;;
    esac
done

# Walk up from CWD to the project root (pom.xml / build.gradle[.kts]).
ROOT="$(pwd)"
while [ "$ROOT" != "/" ] \
    && [ ! -f "$ROOT/pom.xml" ] \
    && [ ! -f "$ROOT/build.gradle" ] \
    && [ ! -f "$ROOT/build.gradle.kts" ]; do
    ROOT="$(dirname "$ROOT")"
done
if [ ! -f "$ROOT/pom.xml" ] && [ ! -f "$ROOT/build.gradle" ] \
    && [ ! -f "$ROOT/build.gradle.kts" ]; then
    echo "✗ No Maven/Gradle build file found in this directory tree" >&2
    exit 1
fi
cd "$ROOT" || exit 1

REPORT_HTML=""
COVERAGE=""

echo "═══ Coverage (JaCoCo) ═══"
if [ -f "pom.xml" ]; then
    if ! grep -q "jacoco" pom.xml; then
        echo "✗ JaCoCo not configured in pom.xml — add org.jacoco:jacoco-maven-plugin (with jacoco:report) to enable the coverage gate." >&2
        exit 1
    fi
    if ! command -v mvn >/dev/null 2>&1; then
        echo "✗ mvn not found on PATH" >&2
        exit 1
    fi
    mvn test -q >/dev/null 2>&1 || true
    mvn jacoco:report -q >/dev/null 2>&1 || true
    REPORT_HTML="target/site/jacoco/index.html"
    XML_ARTIFACT="target/site/jacoco/jacoco.xml"
elif [ -f "build.gradle" ] || [ -f "build.gradle.kts" ]; then
    if ! grep -q "jacoco" build.gradle build.gradle.kts 2>/dev/null; then
        echo "✗ JaCoCo not configured in the Gradle build — add the org.gradle.jacoco plugin to enable the coverage gate." >&2
        exit 1
    fi
    if ! command -v gradle >/dev/null 2>&1; then
        echo "✗ gradle not found on PATH" >&2
        exit 1
    fi
    gradle test jacocoTestReport -q >/dev/null 2>&1 || true
    REPORT_HTML="build/reports/jacoco/test/html/index.html"
    XML_ARTIFACT="build/reports/jacoco/test/jacocoTestReport.xml"
fi

if [ -f "$REPORT_HTML" ]; then
    COVERAGE="$(grep -oP 'Total.*?([0-9]+)%' "$REPORT_HTML" 2>/dev/null | grep -oP '[0-9]+' | head -1 || echo "")"
fi
echo ""
echo "Line coverage: ${COVERAGE:-unavailable}% (threshold: ${COVERAGE_THRESHOLD}%)"

if [ -z "$COVERAGE" ]; then
    echo "✗ JaCoCo report not found / percentage not detected at ${REPORT_HTML}" >&2
    exit 1
fi

if [ "$LCOV" -eq 1 ]; then
    if [ -f "$XML_ARTIFACT" ]; then
        echo "jacoco report artifact kept: $XML_ARTIFACT"
    else
        echo "⚠️  jacoco.xml artifact not found at ${XML_ARTIFACT}" >&2
    fi
fi

if [ "$GATE" -eq 1 ]; then
    if [ "$COVERAGE" -ge "$COVERAGE_THRESHOLD" ] 2>/dev/null; then
        echo "✓ Coverage gate passed"
    else
        echo "✗ Coverage below threshold (${COVERAGE}% < ${COVERAGE_THRESHOLD}%)" >&2
        exit 1
    fi
fi
exit 0
