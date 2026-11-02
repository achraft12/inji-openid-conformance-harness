# syntax=docker/dockerfile:1.7
FROM maven:3.9.9-eclipse-temurin-21 AS build
WORKDIR /src/verify
COPY upstream/inji-verify/ ./
RUN --mount=type=cache,target=/root/.m2,sharing=locked \
    mvn -B -ntp -pl verify-service -am -Dmaven.test.skip=true \
      -Dgpg.skip=true -Dmaven.javadoc.skip=true package

FROM eclipse-temurin:21-jre
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -g 10001 harness && useradd -u 10001 -g harness -m harness
COPY .runtime/tls/ca.crt /tls/ca.crt
RUN keytool -importcert -noprompt -cacerts -storepass changeit -alias inji-conformance -file /tls/ca.crt
COPY --from=build /src/verify/verify-service/target/verify-service-*-exec.jar /app/verify.jar
COPY sources.lock.json /app/sources.lock.json
USER harness
EXPOSE 8080
ENTRYPOINT ["java", "-Dspring.cloud.config.enabled=false", "-Dspring.cloud.bootstrap.enabled=false", "-jar", "/app/verify.jar", "--spring.profiles.active=default"]
