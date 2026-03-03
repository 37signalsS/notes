# Glibc vs Musl

## Определения

**Стандартная библиотека C (libc)** — ключевой компонент POSIX-совместимых ОС, предоставляющий базовые функции: системные вызовы, управление памятью, ввод-вывод, работа со строками.

**Доминирующие реализации в Linux:**

- **Glibc (GNU C Library)** — стандарт де-факто для большинства дистрибутивов
- **Musl libc** — легковесная альтернатива для контейнеров и встраиваемых систем

## Основные концепции

### Философия дизайна

| Аспект | Glibc | Musl |
| :--- | :--- | :--- |
| **Философия** | Полнота и совместимость | Минимализм, корректность, простота |
| **Стандарт** | POSIX + расширения GNU | Строгий POSIX |
| **Целевая аудитория** | Десктопы, серверы общего назначения | Контейнеры, встраиваемые системы |
| **Размер** | Значительно больше | Очень маленький |
| **Статическая линковка** | Проблематична | Идеально |

## Практические сценарии

### 1. Статические бинарные файлы для контейнеров

**Musl** — идеальный выбор для легковесных переносимых образов:

```bash
# Сборка статического бинарника с musl
musl-gcc -static myapp.c -o myapp

# Проверка типа бинарного файла
file myapp
# Вывод: "statically linked"

# Размер: ~500 КБ vs ~2 МБ для glibc
ls -lh myapp
```

**Применение:**

- Alpine Linux образы
- Distroless контейнеры
- Однобинаторные приложения (Go, Rust)

### 2. Десктопы и серверы общего назначения

**Glibc** — выбор по умолчанию:

- Подавляющее ПО собирается и тестируется с glibc
- Максимальная совместимость
- Поддержка расширений GNU

**Дистрибутивы:** Debian, Ubuntu, Fedora, RHEL, CentOS

### 3. Встраиваемые системы

**Musl** предпочтителен для:

- Устройств с ограниченной памятью
- Требований к быстрому старту
- Статической линковки без зависимостей

**Примеры:** OpenWrt, Void Linux (musl variant)

## Дополнительная информация

### Технические различия

| Аспект | Glibc | Musl |
| :--- | :--- | :--- |
| **Статическое связывание** | Проблематично: NSS загружает `.so` динамически | Идеально: по-настоящему статические бинарники |
| **Совместимость** | Максимальная: стандарт для Debian, Fedora, RHEL | Высокая, но не полная: проблемы с GNU-расширениями |
| **DNS (getaddrinfo)** | Комплексное: NSS через `/etc/nsswitch.conf` | Простое: прямой DNS-клиент |
| **malloc** | ptmalloc: многофункциональный, возможна фрагментация | mallocng: быстрый, низкое потребление памяти |
| **Потоки** | NPTL: тесная интеграция с ядром | Собственная реализация: легковесная |
| **Размер** | ~2 МБ (динамический), ~8 МБ (статический) | ~300 КБ (динамический), ~800 КБ (статический) |
| **Локали** | Полная поддержка | Ограниченная поддержка |
| **Производительность** | Оптимизирован для общих нагрузок | Оптимизирован для предсказуемости |

### Проблемы совместимости

#### Glibc → Alpine (musl)

**Ошибка:**

```
bash: ./myapp: No such file or directory
# Или:
error while loading shared libraries: libc.so.6: cannot open shared object file
```

**Причина:** Бинарник скомпилирован с glibc, в Alpine используется musl.

**Решения:**

1. **Пересобрать с musl:**

   ```dockerfile
   FROM alpine:latest
   RUN apk add --no-cache gcc musl-dev
   COPY myapp.c .
   RUN musl-gcc -static myapp.c -o myapp
   CMD ["./myapp"]
   ```

2. **Использовать glibc в Alpine (компромисс):**

   ```dockerfile
   FROM alpine:latest
   ENV GLIBC_VERSION="2.35-r1"
   RUN wget "https://github.com/sgerrand/alpine-pkg-glibc/releases/download/${GLIBC_VERSION}/glibc-${GLIBC_VERSION}.apk" && \
       apk add --no-cache glibc-${GLIBC_VERSION}.apk
   COPY ./my-glibc-app /usr/local/bin/
   ```

3. **Многоэтапная сборка со статической линковкой:**

   ```dockerfile
   # Этап сборки
   FROM golang:1.21 AS builder
   ENV CGO_ENABLED=0
   RUN go build -o myapp .

   # Финальный образ
   FROM alpine:latest
   COPY --from=builder /go/myapp /usr/local/bin/
   CMD ["myapp"]
   ```

### Связанные темы

- **[Alpine Dockerfile](../../Docker/Dockerfile/dockerfile_alpine_linux.md)** — использование Alpine в Docker
- **[Distroless Images](../../Docker/Dockerfile/Docker_best_practices/security.md)** — минималистичные образы
- **[Glibc Compatibility](../../Docker/Docker_troubleshooting/alpine_glibc_compatibility.md)** — troubleshooting совместимости

### Дополнительные ресурсы

- **Glibc Manual:** [gnu.org/software/libc/manual](https://www.gnu.org/software/libc/manual/)
- **Musl Homepage:** [musl.libc.org](https://musl.libc.org/)
- **Alpine Linux:** [alpinelinux.org](https://alpinelinux.org/)
- **Static Linking Issues:** [github.com/golang/go/issues/12634](https://github.com/golang/go/issues/12634)
