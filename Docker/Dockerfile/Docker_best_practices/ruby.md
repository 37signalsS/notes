# Dockerfile: Лучшие практики для Ruby on Rails

## Multi-stage сборка для Ruby on Rails
```dockerfile
FROM ruby:3.4.6-slim-bookworm AS builder
RUN apt-get update -qq && \
    apt-get install --no-install-recommends -y build-essential git libpq-dev
WORKDIR /usr/src/app
RUN gem install bundler
COPY Gemfile Gemfile.lock ./
RUN bundle config set --local without 'development test' && \
    bundle install --jobs $(nproc) --retry 3

FROM ruby:3.4.6-slim-bookworm
RUN apt-get update -qq && \
    apt-get install --no-install-recommends -y curl libpq5 postgresql-client && \
    rm -rf /var/lib/apt/lists/*
WORKDIR /usr/src/app
COPY --from=builder /usr/local/bundle/ /usr/local/bundle/
COPY . .
RUN useradd -m --uid 1001 rails
USER rails
EXPOSE 3000
CMD ["bundle", "exec", "puma", "-C", "config/puma.rb"]
```

## Оптимизированный Dockerfile для Ruby on Rails (Alpine)
```dockerfile
FROM ruby:3.3-alpine
RUN set -ex && \
    apk add --update --virtual .runtime-deps \
        postgresql-client \
        nodejs \
        libffi-dev \
        readline \
        sqlite && \
    rm -rf /var/cache/apk/*
WORKDIR /tmp
COPY Gemfile Gemfile.lock ./
RUN set -ex && \
    apk add --virtual .build-deps \
        build-base \
        openssl-dev \
        postgresql-dev \
        libc-dev \
        linux-headers \
        libxml2-dev \
        libxslt-dev \
        readline-dev && \
    bundle install --clean --no-cache --without development test --jobs=$(getconf _NPROCESSORS_ONLN) && \
    rm -rf /var/cache/apk/* && \
    apk del .build-deps
ENV APP_HOME /app
COPY . $APP_HOME
WORKDIR $APP_HOME
ENV RAILS_ENV=production RACK_ENV=production
EXPOSE 3000
CMD ["bundle", "exec", "puma"]
```
