# syntax=docker/dockerfile:1.7
FROM maven:3.9.9-eclipse-temurin-21 AS build
WORKDIR /src/oidf
COPY upstream/conformance-suite/ ./
RUN --mount=type=cache,target=/root/.m2,sharing=locked \
    mvn -B -ntp -Dmaven.test.skip=true -Dpmd.skip=true -Dcheckstyle.skip=true package

FROM eclipse-temurin:21-jre
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -g 10001 harness && useradd -u 10001 -g harness -m harness
COPY .runtime/tls/ca.crt /tls/ca.crt
RUN keytool -importcert -noprompt -cacerts -storepass changeit -alias inji-conformance -file /tls/ca.crt
COPY --from=build /src/oidf/target/fapi-test-suite.jar /app/oidf.jar
COPY sources.lock.json /app/sources.lock.json
USER harness
EXPOSE 8080
ENTRYPOINT ["java", "-Djdk.tls.maxHandshakeMessageSize=65536", "-jar", "/app/oidf.jar", "--fintechlabs.base_url=https://oidf.conformance.test:8443", "--fintechlabs.base_mtls_url=https://oidf.conformance.test:8444", "--spring.mongodb.uri=mongodb://oidf-mongo:27017/test_suite", "--fintechlabs.devmode=true"]
