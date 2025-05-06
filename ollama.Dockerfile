FROM ollama/ollama:latest

USER root

# Install curl using the package manager (likely apt for Debian-based images)
# RUN apk add --no-cache curl # Use this line instead if the image is Alpine-based
RUN apt-get update && \
    apt-get install -y curl && \
    rm -rf /var/lib/apt/lists/*