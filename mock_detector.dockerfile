FROM base_node:latest

ADD ./mock_detector /app
ENV PYTHONPATH "${PYTHONPATH}:/app:/usr/local/lib/python3.7/site-packages:/learning_loop_node/learning_loop_node"
ENV TZ=Europe/Amsterdam
EXPOSE 80
