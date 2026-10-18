# CI/CD автоматизация: статический анализ (Gixy-Next), тестирование и безопасный деплой Nginx

**Актуально для:** Nginx 1.26+ (OSS/Plus), Angie 1.6+, Gixy-Next 0.2+, Docker 26+, GitLab CI / GitHub Actions

---

## 0. Декларация перекрытия (Overlap Declaration)

Настоящий документ является единым источником правды (SSoT) по методологии тестирования, статического анализа безопасности и организации безопасного пайплайна развертывания конфигураций Nginx в CI/CD:
- [Core/nginx_setup.md](../Core/nginx_setup.md) — содержит краткий 10-строчный базовый сниппет запуска `nginx -t` в GitLab CI без статического анализа безопасности и без интеграционных тестов.
- [Security/nginx_security_guide.md](../Security/nginx_security_guide.md) — описывает уязвимости конфигураций (Off-by-slash, SSRF, Request Smuggling), но не рассматривает инструментарий их автоматизированного поиска в пайплайне.
- [Scenarios/nginx_in_docker.md](../Scenarios/nginx_in_docker.md) — фокусируется на контейнеризации и `envsubst`, не затрагивая сквозной пайплайн сборки и доставки конфигураций.

---

## 1. Определения

- **Синтаксическая валидация (`nginx -t`)** — проверка синтаксиса конфигурационных файлов и доступности указанных путей (сертификатов, сокетов, логов) встроенным бинарным парсером Nginx. Не выявляет логические и архитектурные дефекты безопасности.
- **Статический анализ безопасности (AST Linting / Gixy-Next)** — анализ синтаксического дерева конфигураций Nginx без запуска сервера. Позволяет обнаруживать уязвимости (Off-by-slash, Server-Side Request Forgery, Response Splitting, утечки заголовков, небезопасные регулярные выражения).
- **Gixy-Next** — поддерживаемый открытый форк оригинального анализатора Gixy (Yandex) на базе Python 3, адаптированный под современные директивы Nginx и Angie.
- **Интеграционное тестирование маршрутизации (Dynamic Routing Test)** — автоматизированная проверка сквозного прохождения запросов через изолированный эфемерный контейнер с боевой конфигурацией с валидацией статус-кодов, заголовков и редиректов утилитами `curl` или `pytest`.
- **Атомарный деплой (Atomic Configuration Deployment)** — процедура выкатки, при которой новая конфигурация сначала валидируется на целевом сервере в изолированном временном каталоге, и только при успешном прохождении тестов атомарно подменяет боевой каталог с последующим плавным сигналом `HUP` (`reload`).

---

## 2. Архитектура пирамиды тестирования конфигураций Nginx

Полагаться исключительно на команду `nginx -t` в production-окружениях недопустимо:
1. `nginx -t` вернет `syntax is ok`, даже если префиксный `location /static` содержит критическую уязвимость выхода за пределы каталога (Off-by-slash в `alias`).
2. `nginx -t` вернет `test is successful`, даже если директива `proxy_pass http://$backend` создает открытый SSRF-прокси.
3. `nginx -t` не проверяет работоспособность цепочки редиректов, заголовков CORS и параметров HSTS.

Промышленный стандарт автоматизации Nginx строится по **трехуровневой пирамиде валидации**:

```text
               ▲
              / \
             /   \     Уровень 3: Динамические интеграционные тесты
            /     \    (Эфемерный Docker-контейнер + curl / pytest / testinfra)
           /───────\
          /         \   Уровень 2: Статический анализ безопасности AST
         /           \  (Gixy-Next: аудит Off-by-slash, SSRF, Response Splitting)
        /─────────────\
       /               \ Уровень 1: Синтаксис ядра Nginx
      /                 \ (nginx -t / nginx -T в CI-раннере)
     /───────────────────\
```

---

## 3. Практические сценарии реализации

### Сценарий 1: Настройка статического анализатора Gixy-Next

Установка в окружении CI/CD (или локально инженером):

```bash
# Установка актуальной версии Gixy-Next
python3 -m pip install --upgrade pip
pip install gixy-next

# Запуск анализа основного файла
gixy /etc/nginx/nginx.conf
```

Пример файла конфигурации исключений `.gixy.json` (размещается в корне репозитория для подавления известных ложных срабатываний):
```json
{
  "include": [
    "/etc/nginx/nginx.conf",
    "/etc/nginx/conf.d/*.conf"
  ],
  "skip": [
    "http_splitting"
  ],
  "rules": {
    "ssrf": {
      "disabled": false
    },
    "origins": {
      "disabled": false
    }
  }
}
```

Подавление ложных срабатываний непосредственно в конфигурационном файле Nginx через комментарий:
```nginx
location /dynamic-proxy/ {
    # gixy: disable=ssrf Reason: Внутренний проверенный DNS-резолвер
    proxy_pass http://$target_host;
}
```

---

### Сценарий 2: Полнофункциональный пайплайн в GitLab CI (`.gitlab-ci.yml`)

Пайплайн включает все три уровня пирамиды тестирования и безопасную атомарную доставку:

```yaml
# .gitlab-ci.yml
stages:
  - syntax-and-lint
  - integration-test
  - deploy

variables:
  NGINX_IMAGE: "nginx:1.26-alpine"

# Уровень 1 и 2: Проверка синтаксиса и AST-анализ
lint:nginx:
  stage: syntax-and-lint
  image: python:3.11-alpine
  before_script:
    - apk add --no-cache nginx git
    - pip install --no-cache-dir gixy-next
  script:
    - echo "=== Шаг 1.1: Проверка синтаксиса ядра ==="
    - nginx -t -c $CI_PROJECT_DIR/nginx.conf
    - echo "=== Шаг 1.2: Дамп полной конфигурации для проверки include ==="
    - nginx -T -c $CI_PROJECT_DIR/nginx.conf > /tmp/full_nginx_dump.conf
    - echo "=== Шаг 2.0: Статический анализ безопасности Gixy-Next ==="
    - gixy /tmp/full_nginx_dump.conf

# Уровень 3: Интеграционное динамическое тестирование в Docker
test:routing:
  stage: integration-test
  image: docker:26-cli
  services:
    - docker:26-dind
  script:
    - echo "=== Запуск эфемерного тестового экземпляра Nginx ==="
    - docker run -d --name nginx-test -p 8080:80 -p 8443:443 -v $CI_PROJECT_DIR:/etc/nginx:ro $NGINX_IMAGE
    - sleep 2
    - docker ps | grep nginx-test
    
    - echo "=== Проверка доступности Healthcheck эндпоинта ==="
    - docker run --rm --network host curlimages/curl:latest -sS -f http://127.0.0.1:8080/healthz || exit 1
    
    - echo "=== Проверка принудительного редиректа с HTTP на HTTPS ==="
    - HTTP_CODE=$(docker run --rm --network host curlimages/curl:latest -s -o /dev/null -w "%{http_code}" -H "Host: company.com" http://127.0.0.1:8080/)
    - if [ "$HTTP_CODE" != "301" ]; then echo "Ошибка: Ожидался 301 Redirect, получен $HTTP_CODE"; exit 1; fi
    
    - echo "=== Проверка защиты от прямого доступа по IP (дефолтный хост) ==="
    - IP_STATUS=$(docker run --rm --network host curlimages/curl:latest -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8080/)
    - if [ "$IP_STATUS" != "444" ] && [ "$IP_STATUS" != "403" ]; then echo "Ошибка: Дефолтный хост вернул $IP_STATUS вместо 444/403"; exit 1; fi
    
    - echo "=== Очистка тестового стенда ==="
    - docker stop nginx-test && docker rm nginx-test

# Безопасный атомарный деплой на production-ноды
deploy:production:
  stage: deploy
  image: alpine:latest
  before_script:
    - apk add --no-cache openssh-client rsync bash
    - eval $(ssh-agent -s)
    - echo "$SSH_PRIVATE_KEY" | tr -d '\r' | ssh-add -
    - mkdir -p ~/.ssh && chmod 700 ~/.ssh
    - ssh-keyscan -H "$PROD_HOST" >> ~/.ssh/known_hosts
  script:
    - echo "=== Запуск скрипта безопасного атомарного обновления на $PROD_HOST ==="
    - rsync -az --delete $CI_PROJECT_DIR/conf.d/ root@$PROD_HOST:/etc/nginx/conf.d.next/
    - ssh root@$PROD_HOST "/usr/local/bin/nginx-atomic-reload.sh"
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
      when: manual
```

---

### Сценарий 3: Скрипт безопасного атомарного обновления (`nginx-atomic-reload.sh`)

Скрипт размещается на боевых серверах балансировщиков (`/usr/local/bin/nginx-atomic-reload.sh`) и вызывается из пайплайна:

```bash
#!/usr/bin/env bash
set -Eeuo pipefail

# Конфигурационные пути
CONF_DIR="/etc/nginx/conf.d"
NEXT_DIR="/etc/nginx/conf.d.next"
BACKUP_DIR="/etc/nginx/conf.d.bak"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

if [ ! -d "$NEXT_DIR" ]; then
    log "ОШИБКА: Каталог с новыми конфигурациями $NEXT_DIR не существует!"
    exit 1
fi

log "Этап 1: Валидация новой конфигурации во временном контексте..."
# Создаем временную структуру для тестирования связки
TEST_TMP=$(mktemp -d /tmp/nginx-test.XXXXXX)
trap 'rm -rf "$TEST_TMP"' EXIT

cp -r /etc/nginx/* "$TEST_TMP/"
rm -rf "$TEST_TMP/conf.d"
cp -r "$NEXT_DIR" "$TEST_TMP/conf.d"

# Проверка синтаксиса и связей внутри тестовой структуры
if ! nginx -t -c "$TEST_TMP/nginx.conf" > /dev/null 2>&1; then
    log "КРИТИЧЕСКАЯ ОШИБКА: Валидация новой конфигурации не прошла!"
    nginx -t -c "$TEST_TMP/nginx.conf"
    exit 2
fi

log "Этап 2: Атомарная ротация каталогов..."
# Бэкап текущего рабочего состояния
rm -rf "$BACKUP_DIR"
cp -r "$CONF_DIR" "$BACKUP_DIR"

# Атомарная замена через замену содержимого
rsync -a --delete "$NEXT_DIR/" "$CONF_DIR/"
rm -rf "$NEXT_DIR"

log "Этап 3: Финальная проверка боевого каталога перед сигналом..."
if ! nginx -t > /dev/null 2>&1; then
    log "ВНИМАНИЕ: Ошибка боевого каталога! Автоматический откат к бэкапу..."
    rsync -a --delete "$BACKUP_DIR/" "$CONF_DIR/"
    nginx -t
    exit 3
fi

log "Этап 4: Плавное перечитывание конфигурации (Zero-Downtime Reload)..."
systemctl reload nginx

log "УСПЕХ: Конфигурация Nginx успешно обновлена без простоя сервиса."
```

---

### Сценарий 4: Тестирование динамической маршрутизации на Python (Pytest + Testinfra)

Для сложных инфраструктур API Gateway проверки выполняются структурированными тестами `pytest`:

```python
# tests/test_nginx_routing.py
import pytest
import requests

BASE_URL = "http://127.0.0.1:8080"

def test_healthz_endpoint():
    response = requests.get(f"{BASE_URL}/healthz", timeout=2)
    assert response.status_code == 200
    assert response.text.strip() == "OK"

def test_security_headers_present():
    response = requests.get(f"{BASE_URL}/api/v1/ping", headers={"Host": "api.company.com"}, timeout=2)
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Frame-Options") == "DENY"
    assert "X-Request-ID" in response.headers

def test_off_by_slash_protection():
    # Проверка: запрос к /static.. /admin не должен выходить за пределы каталога
    response = requests.get(f"{BASE_URL}/static../etc/passwd", timeout=2)
    assert response.status_code in [400, 403, 404]

def test_rate_limiting_trigger():
    # Проверка срабатывания лимита скорости: отправка 50 быстрых запросов
    statuses = []
    for _ in range(50):
        res = requests.get(f"{BASE_URL}/api/v1/resource", headers={"Host": "api.company.com"})
        statuses.append(res.status_code)
    
    assert 429 in statuses or 503 in statuses
```

Запуск в CI-раннере:
```bash
pytest -v tests/test_nginx_routing.py
```

---

## 4. Типичные проблемы и траблшутинг

| Ошибка в пайплайне | Причина | Способ диагностики | Решение |
|---|---|---|---|
| **`[emerg] open() ... failed (2: No such file or directory)` на шаге `nginx -t` в CI** | В репозитории лежат относительные `include` или в контейнере раннера отсутствуют SSL-сертификаты (`/etc/ssl/certs/...`). | Лог шага `lint:nginx` в CI. | Монтировать фиктивные (self-signed) сертификаты-заглушки в контейнере раннера для этапа проверки синтаксиса. |
| **Ложное срабатывание Gixy: `SSRF via variable in proxy_pass`** | Gixy считает небезопасным любой `proxy_pass http://$var;`, даже если переменная вычисляется из безопасного `map`. | Отчет Gixy с указанием правила `ssrf`. | Добавить маркер `# gixy: disable=ssrf` перед проблемной строкой либо внести исключение в `.gixy.json`. |
| **`nginx -t` успешен, но `systemctl reload` зависает** | Воркеры не могут закрыть слушающие сокеты из-за незавершающихся keepalive-соединений или долгого стриминга (`worker_shutdown_timeout` не задан). | `systemctl status nginx`, зависшие процессы воркеров в статусе `is shutting down`. | Задать в `nginx.conf`: `worker_shutdown_timeout 15s;`. |
| **Рассинхронизация конфигураций при наличии нескольких нод балансировщиков** | Выкатка завершилась успешно на узле 1, но упала на узле 2 из-за разницы локальных путей. | Расхождение контрольных сумм: `md5sum /etc/nginx/nginx.conf`. | Использовать атомарный деплой через Ansible с параметром `serial: 1` или blue-green переключение VIP. |

---

## 5. Лучшие практики (Best Practices)

1. **Никогда не делайте прямой `git pull` в рабочий каталог `/etc/nginx/` на production-серверах.** Любая незавершенная передача файлов или синтаксическая ошибка мгновенно сломает последующий аварийный reload или авторестарт systemd.
2. **Всегда формируйте полный дамп через `nginx -T` перед статическим анализом.** Это разворачивает все директивы `include`, исключая пропуск файлов виртуальных хостов при аудите.
3. **Разделяйте проверки на быстрые (pre-commit) и полные (CI/CD):**
   * *Локальный pre-commit hook разработчика:* запуск линтера синтаксиса `nginx -t` в Docker (1 секунда).
   * *CI/CD пайплайн в репозитории:* Gixy-Next + интеграционные тесты динамики (15–30 секунд).
4. **Контролируйте права на развернутые файлы:**
   ```bash
   sudo chown -R root:root /etc/nginx
   sudo find /etc/nginx -type d -exec chmod 755 {} \;
   sudo find /etc/nginx -type f -exec chmod 644 {} \;
   ```
5. **Используйте Zero-Downtime Reload (`systemctl reload nginx`):** Никогда не используйте `restart` в автоматизированных пайплайнах, чтобы исключить сброс текущих TCP-сессий пользователей.

---

## 6. Дополнительная информация

- [Базовая установка и управление процессами Nginx](../Core/nginx_setup.md) — управление демоном через systemd и сигналы.
- [Руководство по безопасности Nginx](../Security/nginx_security_guide.md) — перечень уязвимостей L7 и стандарты защиты.
- [Бесшовное обновление исполняемого файла бинарника Nginx](../Core/nginx_build_from_source.md) — обновление самого веб-сервера без простоя по сигналу `SIGUSR2`.
- [Полезные ссылки и инструменты экосистемы](../../webservers_useful_links.md) — репозитории Gixy-Next и утилиты инспекции TLS.
