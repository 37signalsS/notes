# Ошибка "file not found" в Alpine для скомпилированного бинарного файла

**Проблема:** Бинарный файл, скомпилированный в Ubuntu/Debian, не запускается в Alpine с ошибкой `file not found` или `error while loading shared libraries`.

**Причина:** Несовместимость стандартных библиотек C. В большинстве дистрибутивов используется `glibc`, а в Alpine — легковесная `musl libc`.

**Решение 1 (Лучшее):** Пересобрать приложение в `alpine`-образе, используя многоэтапную сборку.

**Решение 2 (Компромисс):** Установить `glibc` в Alpine.

```dockerfile
FROM alpine:3.22.1

ENV GLIBC_VERSION="2.35-r1"
RUN apk add --no-cache wget ca-certificates && \
    wget -q -O /etc/apk/keys/sgerrand.rsa.pub https://alpine-pkgs.sgerrand.com/sgerrand.rsa.pub && \
    wget "https://github.com/sgerrand/alpine-pkg-glibc/releases/download/${GLIBC_VERSION}/glibc-${GLIBC_VERSION}.apk" && \
    apk add --no-cache glibc-${GLIBC_VERSION}.apk && rm -f glibc-*.apk

# Теперь можно запускать glibc-совместимые приложения
COPY ./my-glibc-app /usr/local/bin/
CMD ["my-glibc-app"]
```
