#!/usr/bin/env bash
# ============================================================================
# install_coverage_tools.sh — Java: JaCoCo is configured in the build, not
# installed
#
# Enables/verifies the JaCoCo plugin for Maven or Gradle. The coverage gate
# (.pi/scripts/languages/java/coverage.sh) reads its HTML/XML reports.
# ============================================================================
set -euo pipefail

if [ -f "pom.xml" ]; then
    if grep -q "jacoco" pom.xml; then
        echo "JaCoCo already configured in pom.xml."
    else
        echo "Adding org.jacoco:jacoco-maven-plugin to pom.xml requires an edit — add to <build><plugins>:"
        cat <<'EOF'
  <plugin>
    <groupId>org.jacoco</groupId>
    <artifactId>jacoco-maven-plugin</artifactId>
    <version>0.8.12</version>
    <executions><execution><goals><goal>prepare-agent</goal><goal>report</goal></goals></execution></executions>
  </plugin>
EOF
        echo "✗ Not editing pom.xml automatically — apply the snippet above, then re-run." >&2
        exit 1
    fi
elif [ -f "build.gradle" ] || [ -f "build.gradle.kts" ]; then
    if grep -q "jacoco" build.gradle build.gradle.kts 2>/dev/null; then
        echo "JaCoCo already configured in the Gradle build."
    else
        echo "Add to build.gradle:  apply plugin: 'jacoco'   (then: gradle jacocoTestReport)" >&2
        echo "✗ Not editing the Gradle build automatically — apply the plugin, then re-run." >&2
        exit 1
    fi
else
    echo "✗ No Maven/Gradle build file found" >&2
    exit 1
fi

echo "JaCoCo coverage tooling ready."
