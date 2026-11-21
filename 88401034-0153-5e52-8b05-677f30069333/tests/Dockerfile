FROM public.ecr.aws/d4u1d3p6/godzilla:smoldata-verifier-base-20261120@sha256:155c0866b088182ece7732df9c2bc3b4d61b5c5a93b6ec49c35a7dbb7d2a3a67
COPY . /tests/
RUN mkdir -p /opt/grader \
 && mv /tests/evaluator.py /tests/task_metadata.json /tests/hidden_tests /opt/grader/ \
 && chmod -R go-rwx /opt/grader \
 && rm -f /tests/Dockerfile /tests/requirements.lock.txt /tests/base-requirements.txt && chmod +x /tests/test.sh
ENV PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
USER root
