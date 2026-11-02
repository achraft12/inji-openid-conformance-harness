FROM python:3.13.7-alpine
WORKDIR /harness
RUN pip install --no-cache-dir httpx==0.28.1 pyparsing==3.2.5
COPY scripts/certify_runner.py scripts/probe.py /harness/scripts/
COPY upstream/conformance-suite/scripts/conformance.py upstream/conformance-suite/scripts/test_plan_parser.py /harness/upstream/conformance-suite/scripts/
COPY config/certify-metadata.json config/certify-preauthorized.json config/benchmark.json /harness/config/
COPY sources.lock.json /harness/sources.lock.json
ENTRYPOINT ["python", "-u", "/harness/scripts/certify_runner.py"]
