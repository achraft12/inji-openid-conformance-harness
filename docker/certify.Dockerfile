# syntax=docker/dockerfile:1.7
FROM maven:3.9.9-eclipse-temurin-21 AS build
WORKDIR /src
# Certify embeds verify-core at a SNAPSHOT version. Resolve it from our pinned
# Verify checkout, instead of silently downloading a different implementation.
COPY upstream/inji-verify/ /src/verify/
RUN --mount=type=cache,target=/root/.m2,sharing=locked \
    mvn -B -ntp -f verify/pom.xml -pl verify-core -am \
      -Dmaven.test.skip=true -Dgpg.skip=true -Dmaven.javadoc.skip=true install
COPY upstream/inji-certify/ /src/certify/
RUN --mount=type=cache,target=/root/.m2,sharing=locked \
    mvn -B -ntp -f certify/pom.xml -pl certify-service -am \
      -Dmaven.test.skip=true -Dgpg.skip=true -Dmaven.javadoc.skip=true package

FROM eclipse-temurin:21-jre
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -g 10001 harness && useradd -u 10001 -g harness -m harness \
    && mkdir /keys && chown harness:harness /keys
COPY .runtime/tls/ca.crt /tls/ca.crt
RUN keytool -importcert -noprompt -cacerts -storepass changeit -alias inji-conformance -file /tls/ca.crt
COPY --from=build /src/certify/certify-service/target/certify-service-*.jar /app/certify.jar
COPY sources.lock.json /app/sources.lock.json
USER harness
EXPOSE 8090
ENTRYPOINT ["java", "-Dspring.cloud.bootstrap.enabled=false", "-Dspring.cloud.config.enabled=false", "-jar", "/app/certify.jar", "--spring.config.location=file:/config/certify.properties"]
