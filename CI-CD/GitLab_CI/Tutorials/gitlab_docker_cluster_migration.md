# Миграция GitLab из одного Docker-контейнера в кластер

**Актуально для:** GitLab 19.x (PostgreSQL 17+, Valkey 7.2+ / Redis 7.2+)

## Определения

* **GitLab CE (Community Edition)** — открытая версия платформы для самостоятельного размещения, включающая полный цикл DevOps: управление исходным кодом, ревью, CI/CD, артефакты и контейнерный реестр.
* **Omnibus GitLab** — официальный Docker-образ, собирающий все компоненты GitLab в один контейнер. Подходит для нагрузок до 20 RPS и 1000 пользователей.
* **Puma** — веб-сервер Ruby, обрабатывающий основной API и веб-интерфейс GitLab.
* **Sidekiq** — многопоточный фоновый обработчик задач на Ruby (уведомления, пайплайны, очистка кэша).
* **Gitaly** — микросервис на Go, управляющий хранением и обработкой всех Git-репозиториев через gRPC.
* **PostgreSQL** — единственная поддерживаемая GitLab СУБД, содержащая метаданные о проектах, пользователях, merge requests и issues.
* **Redis** — in-memory хранилище, используемое для очереди задач Sidekiq, кэширования и пользовательских сессий (в GitLab 19.x — Valkey 7.2+).
* **MinIO** — объектное хранилище, совместимое с S3 API, для артефактов, LFS, пакетов и артефактов CI/CD.
* **HAProxy** — балансировщик нагрузки для распределения трафика между Rails-нодами.
* **GitLab Rails** — монолитное Ruby on Rails приложение, тождественное GitLab в архитектуре Omnibus.

## Введение и обоснование

### Почему кластеризация в Docker, а не новый кластер

По мере роста команды производительности GitLab в одном Docker-контейнере становится недостаточно. Интернет обычно предлагает сразу переезжать на новый кластер — желательно на новом железе. Это отличное, но дорогое решение в плане как развития, так и сопровождения.

Альтернативный подход — кластеризация на базе Docker-контейнеров. Преимущества:

- Изначально GitLab работал в единственном Docker-контейнере. Не переезжаем на новый кластер, а понемногу дорабатываем существующий.
- Всё окружение контейнеризировано (Docker/Podman, k8s). Не дробим ландшафт.
- В контейнерах по умолчанию всё закрыто/отключено, поэтому нужно явно задавать порты и ресурсы. Это помогает глубже понять инструмент.
- Простота отката. Бывают случаи, когда минорный релиз выпущен с ошибкой.
- Информационная безопасность. Отдельные компоненты в контейнере можно обновлять быстрее, чем выйдет новый релиз GitLab.

Такое масштабирование возможно, поскольку в официальном Docker-образе собраны все инструменты, необходимые для работы GitLab. Всё, что нужно сделать — вынести компоненты на отдельные машины, соблюдая принцип разделения ответственности между stateless- и stateful-компонентами.

### Важные ограничения перед началом

- Кластеризуем на примере GitLab 19.x.
- Docker-compose.yml немного упрощены для фокусировки на взаимодействии компонентов.
- В docker-compose.yml и gitlab.rb включены Prometheus-экспортеры, но само подключение к системе мониторинга не описано. Это тема для отдельного обсуждения.
- Централизованный сбор логов и отправка их ELK (или подобный стек) не описаны, но предполагаются. Это тема для отдельного обсуждения.
- Работаем под root, Docker без rootless. На проде rootless удобнее для привязки пользователей ОС с понятными именами. Но это делает примеры слишком громоздкими.
- **Важно:** контейнер — это не виртуальная машина. Обновление операционной системы или пакетов хоста могут повредить данные внутри контейнера.

> **Примечание:** В данном руководстве команды конфигурации `gitlab.rb`, `gitlab-ctl` и `gitlab-backup` приведены в контексте миграции. Для систематического описания управления инстансом, hardening, управления базами данных и масштабирования используйте:
> * **[Управление инстансом GitLab](../Advanced/gitlab_instance_administration.md)**
> * **[Безопасность и закрепление GitLab Server](../Advanced/gitlab_server_security_hardening.md)**
> * **[Управление базами данных GitLab](../Advanced/gitlab_database_management.md)**
> * **[Администрирование GitLab в масштабе](../Advanced/gitlab_administration_at_scale.md)**

## Архитектура и принципы работы

### Когда масштабировать

Omnibus GitLab в одном Docker-контейнере эффективен до 20 RPS и 1000 пользователей. При превышении этих значений проявляются симптомы:
- Медленная отрисовка WebGUI (merge requests, комментарии, issue tracker)
- Задержки при массовом клонировании репозиториев
- Рост времени обработки CI/CD пайплайнов
- Очереди Sidekiq и ошибки 502/504

### Варианты масштабирования

| Компонент | Вынос | Эффект |
| :--- | :--- | :--- |
| PostgreSQL | Внешний контейнер/хост | Нормализация производительности метаданных |
| Redis | Внешний контейнер/хост | Обязательный шаг кластеризации |
| Объектное хранилище | MinIO/S3 | Снижение нагрузки на дисковую подсистему GitLab |
| Gitaly | Выделенный хост с NVMe | Устранение ошибок `Gitaly is unreachable` при массовом клонировании |
| Sidekiq | Отдельные ноды | Обработка тысяч одновременных CI/CD пайплайнов |
| Rails (Puma) | Несколько нод за HAProxy | Горизонтальное масштабирование веб-интерфейса и API |

### Особенности архитектуры

- **CPU для Ruby-компонентов:** количество CPU для Puma и Sidekiq должно быть степенью двойки (2, 4, 8, 16). На конфигурациях с 7/9/12 CPU приложение работает с неполной нагрузкой.
- **Shared memory:** стандартный `shm_size` в Docker (64MB) недостаточен. Для GitLab требуется минимум 256MB, иначе возникают 500-ошибки и `FATAL: could not resize shared memory segment: No space left on device`.
- **Ведомый Rails-инстанс:** в кластере один Rails-инстанс остается ведущим для обновлений, бэкапов и миграций БД. Он размещается на хосте с HAProxy и выводится из пользовательской нагрузки.
- **Максимум Rails:** рекомендуемый максимум на одну ноду — 32 vCPU.

### Итоговая архитектура кластера

После выполнения всех сценариев получаем кластер из ~10 контейнеров, распределённых по хостам согласно таблице ниже.

| Хост | Контейнеры | Роль |
| :--- | :--- | :--- |
| `gitlab-pg-host` | postgres, postgres-exporter | СУБД и метрики |
| `gitlab-redis-host` | valkey/redis, valkey-exporter | Кэш и очереди |
| `gitlab-minio-host` | minio, nginx-minio | Объектное хранилище |
| `gitlab-gitaly-host` | gitlab-gitaly | Git-репозитории |
| `gitlab-sidekiq-host` | gitlab-sidekiq | Фоновые задачи |
| `gitlab-rails-01-host` | gitlab-rails-01 | Rails-нода 1 |
| `gitlab-rails-02-host` | gitlab-rails-02 | Rails-нода 2 |
| `haproxy-host` | gitlab-haproxy, gitlab-rails-main | Балансировщик + ведущий Rails |

## Практические сценарии

### Предварительные требования

**Версии компонентов (GitLab 19.x):**
- PostgreSQL 17.x (минимальная версия для GitLab 19.x; PostgreSQL 16 больше не поддерживается)
- Valkey 7.2+ или Redis 7.2+ (поддержка Redis 6 удалена в GitLab 19.0)
- GitLab CE 19.3.1-ce.0
- Docker Engine 27.0+ / Docker Compose v2.20+
- Хост-ОС: Ubuntu 22.04 LTS / 24.04 LTS или аналогичная с ядром 6.8+

**Сеть:** все контейнеры размещаются в одной bridge-сети `gitlabnet` для взаимодействия по DNS-именам сервисов.

**Важно:** работа демонстрируется под root, Docker без rootless. На проде rootless удобнее для привязки пользователей ОС с понятными именами. Но это делает примеры слишком громоздкими.

Работая с контейнерами, часто забываешь, что контейнер — это не виртуальная машина. И обновление операционной системы или пакетов хоста могут повредить данные внутри контейнера.

### Сценарий 1: Внешний PostgreSQL

PostgreSQL содержит все метаданные и часто становится узким местом при росте команды. Миграция требует запланированного времени недоступности.

#### Подготовка окружения

На хосте `gitlab-pg-host` создайте `/docker/docker-compose/docker-compose.yml`:

```yaml
services:
  postgres:
    image: company-local-docker-images/postgres:16.14
    container_name: gitlab-pg
    logging:
      options:
        max-size: "1g"
        max-file: "5"
    environment:
      POSTGRES_USER: gitlab
      POSTGRES_PASSWORD: "DB_PASSWORD"
      POSTGRES_DB: gitlabhq_production
    shm_size: 1g
    volumes:
      - /docker/postgres/17/data:/var/lib/postgresql/data
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U gitlab -d gitlabhq_production"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 10s
    restart: unless-stopped
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 8G
    networks:
      - gitlabnet

  postgres-exporter:
    image: company-local-docker-images/postgres-exporter:0.17.1
    container_name: pg-exporter
    environment:
      DATA_SOURCE_NAME: "postgresql://gitlab:DB_PASSWORD@postgres:5432/gitlabhq_production?sslmode=disable"
    ports:
      - "9187:9187"
    depends_on:
      - postgres
    networks:
      - gitlabnet

networks:
  gitlabnet:
    driver: bridge
```

`shm_size: 1g` — единственный параметр, который хочу отметить, так как он не описан в документации явно и может приводить к 500-ошибкам в Web GUI или таким ошибкам в логах: `FATAL: could not resize shared memory segment: No space left on device`. По умолчанию Docker выделяет 64 МБ shared memory, которых не хватает даже для GitLab в одном Docker-контейнере. 256 МБ — это необходимый минимум.

Запустите контейнер:

```bash
docker compose -f /docker/docker-compose/docker-compose.yml up -d
```

Дождитесь старта и отредактируйте `/docker/postgres/17/data/postgresql.conf`:

```conf
work_mem  8 MB
maintenance_work_mem 64 MB
max_connections  400
shared_buffers       2 GB
statement_timeout           60000
hot_standby_feedback    on
```

Перезапустите контейнер и проверьте, что можно подключиться к PostgreSQL.

#### Миграция данных

Если все прошло успешно, планируйте прерывание в обслуживании. Без этого вынести PostgreSQL за пределы GitLab не представляется возможным.

Технически перенести данные из одной базы в другую можно без прерывания в обслуживании. Но высок риск потери новых записей, созданных в момент копирования и переключения. Поэтому такой вариант не рассматривается.

Вариантов миграции данных PostgreSQL несколько:

1. **Через rsync** перенести данные с одного хоста на другой:
   ```bash
    rsync -avz -e ssh single-node-gitlab-host@/docker/gitlab/data/postgresql/data/ gitlab-pg-host@/docker/postgres/17/data/
   ```
   Недостаток: при обновлении версии PostgreSQL rsync не поможет, так как формат данных может измениться.

2. **Сделать полный бэкап GitLab** и восстановиться из него после переключения на новую базу:
   ```bash
   docker exec -it single-node-gitlab gitlab-backup create
   ```
   Недостаток: бэкап создаётся долго.

3. **Сделать бэкап базы средствами GitLab** с пропуском больших частей:
   ```bash
   docker exec -it single-node-gitlab gitlab-backup create SKIP=tar,repositories,uploads,builds,artifacts,pages,lfs,terraform_state,registry,packages,ci_secure_files,agent_plan_content,external_diffs
   ```

В первом варианте я не смогу переиспользовать rsync при обновлении версии PostgreSQL, а снимать бэкап долго. Поэтому так я делать не буду, а вместо этого мигрирую данные через создание и восстановление данных докерезированного PostgreSQL.

Вся миграция состоит из двух шагов:

1. Перенести данные в новую базу PostgreSQL.
2. Переключить GitLab на внешний PostgreSQL.

Технически перенести данные из одной базы в другую можно без прерывания в обслуживании. Но высок риск потери новых записей, созданных в момент копирования и переключения. Поэтому я такой вариант не буду рассматривать.

В PostgreSQL пишут два компонента GitLab:

- **Puma** — веб-сервер Ruby-приложений, собственно, сам GitLab. Его процессы мы видим в дереве процессов.
- **Sidekiq** — менеджер очередей на Ruby.

Остановим эти процессы:

```bash
docker exec -t single-node-gitlab pg_dump -U gitlab gitlabhq_production > gitlabdatabase.sql.$(date +%Y-%m-%d"_"%H_%M_%S)
```

2. Оставаясь на той же машине, восстанавливаем бэкап. На случай если на хосте нет `psql`, лучше делать всё через контейнер с GitLab:

```bash
cat gitlabdatabase.sql.$(date +%Y-%m-%d"_"%H_%M_%S) | docker exec -i single-node-gitlab psql -h gitlab-pg-host -U gitlab -d gitlabhq_production
```

3. Проверьте, что восстановление прошло без ошибок и к базе можно подключиться удаленно. Если всё хорошо, отредактируйте конфигурационный файл GitLab `gitlab.rb`. В нашем случае файл будет располагаться в `/docker/gitlab/config/`:

```ruby
# Отключить встроенный PostgreSQL
postgresql['enable'] = false

# Подключение к внешней базе
gitlab_rails['db_adapter'] = 'postgresql'
gitlab_rails['db_encoding'] = 'unicode'
gitlab_rails['db_host'] = 'gitlab-pg-host'
gitlab_rails['db_port'] = 5432
gitlab_rails['db_password'] = 'DB_PASSWORD'
```

4. Сохраните изменения и перезапустите docker-контейнер с GitLab. По моему опыту, процесс миграции редко занимает более 10 минут.

Если получаем 500 ошибку и нет времени на разбор, комментируем ранее запущенные изменения и перезапускаем контейнер. В качестве быстрой диагностики проверьте логи PostgreSQL и доступность порта 5432.

#### Валидация

```bash
# 1. Проверка подключения к PostgreSQL
docker exec -it gitlab-pg psql -U gitlab -d gitlabhq_production -c "SELECT count(*) FROM users;"

# 2. Проверка статуса GitLab
docker exec -t single-node-gitlab gitlab-ctl status

# 3. Проверка здоровья инстанса
docker exec -t single-node-gitlab gitlab-rake gitlab:check SANITIZE=true

# 4. Проверка миграций БД
docker exec -t single-node-gitlab gitlab-rake gitlab:db:migrate:status
```

#### Откат

В случае проблем вернитесь к встроенному PostgreSQL:
1. Остановите `single-node-gitlab`.
2. Восстановите исходный `gitlab.rb` из резервной копии.
3. Запустите контейнер.

#### Особенности работы с внешним PostgreSQL в Docker

**Часовой пояс:** стандартный часовой пояс GitLab — UTC. Не монтируйте `/etc/localtime` в контейнер. При несовпадении часового пояса:
- WebGUI показывает корректное время
- Авторизация через внешние сервисы работает
- В логах ошибок нет
- Но в PostgreSQL данные хранятся с завышением на разницу часовых поясов, что приводит к:
  - Невозможности создания runners через WebGUI (страница с токеном возвращает 404)
  - Остановке создания партиций таблиц
  - Заполнению очередей Sidekiq ошибочными background jobs

**Версия при бэкапе:** GitLab придерживается политики ежегодного обновления версии PostgreSQL. В GitLab 19.x минимальная и единственная поддерживаемая версия — PostgreSQL 17. При миграции с PostgreSQL 16 или обновлении с GitLab 18.x убедитесь, что `pg_dump` соответствует версии 17, иначе резервная копия по `CRON=1 docker exec gitlab-sc gitlab-backup create CRON=1` будет создаваться без дампа базы. Со стороны это не будет видно: изменится только размер, но при ежедневной ротации файлов резервных копий такое быстро выпадает из поля зрения.

### Сценарий 2: Внешний Redis

Redis — самый простой для выноса компонент. В GitLab 19.x в качестве бэкенда по умолчанию используется Valkey 7.2+, совместимый с Redis API. Он хранит очередь задач Sidekiq, кэш и пользовательские сессии. Миграция не требует времени недоступности.

#### Подготовка окружения

На хосте `gitlab-redis-host` создайте `/docker/docker-compose/docker-compose.yml`:

```yaml
services:
  redis:
    image: company-local-docker-images/valkey:7.2.5
    container_name: gitlab-redis
    logging:
      options:
        max-size: "1g"
        max-file: "5"
    volumes:
      - "/docker/redis/data:/data"
    command: valkey-server --bind 0.0.0.0 --requirepass REDIS_PASS --appendonly yes --appendfsync everysec
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "valkey-cli", "-a", "REDIS_PASS", "ping"]
      interval: 30s
      timeout: 10s
      retries: 5
    restart: unless-stopped
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 5G
    networks:
      - gitlabnet

  redis-exporter:
    image: company-local-docker-images/oliver006/redis_exporter:v1.88.0
    container_name: redis_exporter
    environment:
      REDIS_ADDR: "redis://redis:6379"
      REDIS_PASSWORD: "REDIS_PASS"
    ports:
      - "9121:9121"
    restart: unless-stopped
    depends_on:
      - redis
    networks:
      - gitlabnet

networks:
  gitlabnet:
    driver: bridge
```

Запустите стек:

```bash
docker compose -f /docker/docker-compose/docker-compose.yml up -d
```

Проверьте работу Redis:

```bash
docker exec -it gitlab-redis valkey-cli -a REDIS_PASS ping
# → PONG
```

#### Переключение GitLab на внешний Redis

На хосте `single-node-gitlab` отредактируйте `/docker/gitlab/config/gitlab.rb`:

```ruby
redis['enable'] = false
gitlab_rails['redis_host'] = "gitlab-redis-host"
gitlab_rails['redis_port'] = 6379
gitlab_rails['redis_password'] = "REDIS_PASS"
```

Примените конфигурацию:

```bash
docker exec -t single-node-gitlab gitlab-ctl reconfigure
```

Ожидаемое время недоступности — около минуты. Если ошибка 500 не уходит в течение пары минут — откатите изменения и проверяйте логи Sidekiq.

**Важно:** проблемы с Redis/Valkey и PostgreSQL в GitLab проявляются одинаково — ошибкой 500. Для PostgreSQL чаще всего нужно сразу смотреть лог контейнера, для Redis/Valkey — упавшие задачи в очереди Sidekiq.

#### Валидация

```bash
# 1. Проверка работы Valkey
docker exec -it gitlab-redis valkey-cli -a REDIS_PASS ping
# → PONG

# 2. Проверка статуса GitLab
docker exec -t single-node-gitlab gitlab-ctl status

# 3. Проверка очереди Sidekiq
docker exec -t single-node-gitlab gitlab-rake gitlab:sidekiq:check

# 4. Проверка здоровья инстанса
curl -sk https://gitlab.example.com/-/readiness
# → {"status":"ok"}
```

#### Откат

В случае проблем вернитесь к встроенному Valkey/Redis:
1. Остановите `single-node-gitlab`.
2. Восстановите исходный `gitlab.rb` из резервной копии.
3. Запустите контейнер.

### Сценарий 3: Внешнее объектное хранилище (MinIO)

Объектное хранилище — неожиданно самая неоднозначная часть. Рассмотрим миграцию на внешнее объектное хранилище на примере MinIO. Для больших инсталляций GitLab объектное хранилище предпочтительнее расшаренной папки, так как оно заберет на себя часть нагрузки, связанной с объектами LFS, логами CI и артефактами сборок. Почти то же самое можно получить, пошарив между rails-приложениями GitLab и очередями sidekiq папку `/var/opt/gitlab/gitlab-rails/shared` из Docker-контейнера `single-node-gitlab`. На нашем примере на хосте она располагается по пути `/docker/gitlab/data/gitlab-rails/shared/`. Настройку я опишу ниже.

GitLab работает с MinIO только при наличии TLS шифрования. Запросы по HTTP будут игнорироваться. Оборачиваем доступ в Nginx.

#### Подготовка окружения

На хосте `gitlab-minio-host` создайте `/docker/docker-compose/docker-compose.yml`:

```yaml
services:
  minio:
    image: company-local-docker-images/minio:RELEASE.2025-07-18T21-56-31Z-cpuv1
    container_name: gitlab-minio
    command: server /data --console-address ":9001"
    environment:
      - MINIO_ROOT_USER=S3User
      - MINIO_ROOT_PASSWORD=S3Password
    logging:
      options:
        max-size: "10g"
        max-file: "3"
    volumes:
      - "/docker/minio/data:/data"
    restart: unless-stopped
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 7G
    networks:
      - gitlabnet

  nginx-minio:
    image: company-local-docker-images/nginx:1.26.0-perl
    container_name: minio-nginx
    ports:
      - "443:443"
      - "9009:9009"
    volumes:
      - "/docker/nginx/etc/conf.d:/etc/nginx/conf.d"
      - "/opt/ssl:/opt/ssl"
      - "/docker/nginx/log:/var/log/nginx"
    restart: unless-stopped
    networks:
      - gitlabnet

networks:
  gitlabnet:
    driver: bridge
```

#### Конфигурация Nginx

Файл `/docker/nginx/etc/conf.d/minio.conf`:

```nginx
server {
    listen                          80;
    server_name                     gitlab-minio-host;
    return                          301 https://$server_name$request_uri;
}

server {
    listen                          443 ssl;
    listen                          [::]:443;
    server_name                     gitlab-minio-host;

    ignore_invalid_headers off;
    client_max_body_size 0;
    proxy_buffering off;
    proxy_request_buffering off;

    ssl_certificate                 /opt/ssl/my-cert.cer;
    ssl_certificate_key             /opt/ssl/my-cert.key;

    ssl_session_cache               builtin:1000 shared:SSL:10m;
    ssl_protocols                   TLSv1 TLSv1.1 TLSv1.2;
    ssl_ciphers                     HIGH:!aNULL:!eNULL:!EXPORT:!CAMELLIA:!DES:!MD5:!PSK:!RC4;
    ssl_prefer_server_ciphers       on;

    access_log                      /var/log/nginx/gitlab-minio.https.access.log;
    error_log                       /var/log/nginx/gitlab-minio.https.error.log;

    location / {
        proxy_set_header Host $http_host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-NginX-Proxy true;
        real_ip_header X-Real-IP;
        proxy_connect_timeout 300;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        chunked_transfer_encoding off;
        proxy_pass http://minio:9001/;
    }
}

server {
    listen                          9009 ssl;
    listen                          [::]:9009;
    server_name                     gitlab-minio-host;

    ignore_invalid_headers off;
    client_max_body_size 0;
    proxy_buffering off;
    proxy_request_buffering off;

    ssl_certificate                 /opt/ssl/my-cert.cer;
    ssl_certificate_key             /opt/ssl/my-cert.key;

    ssl_session_cache               builtin:1000 shared:SSL:10m;
    ssl_protocols                   TLSv1 TLSv1.1 TLSv1.2;
    ssl_ciphers                     HIGH:!aNULL:!eNULL:!EXPORT:!CAMELLIA:!DES:!MD5:!PSK:!RC4;
    ssl_prefer_server_ciphers       on;

    access_log                      /var/log/nginx/gitlab-minio.https.access.log;
    error_log                       /var/log/nginx/gitlab-minio.https.error.log;

    location / {
        proxy_set_header Host $http_host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-NginX-Proxy true;
        real_ip_header X-Real-IP;
        proxy_connect_timeout 300;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        chunked_transfer_encoding off;
        proxy_pass http://minio:9000/;
    }
}
```

Запустите стек:

```bash
docker compose -f /docker/docker-compose/docker-compose.yml up -d
```

Создайте бакеты вручную через веб-интерфейс MinIO (порт 9001):
- `gl-artifacts`
- `gl-external-diffs`
- `gl-lfs`
- `gl-uploads`
- `gl-packages`
- `gl-dependency-proxy`
- `gl-terraform-state`
- `gl-pages`
- `gl-ci-secure-files`

#### Настройка GitLab

На хосте `single-node-gitlab` отредактируйте `/docker/gitlab/config/gitlab.rb`:

```ruby
gitlab_rails['object_store']['enabled'] = true
gitlab_rails['object_store']['proxy_download'] = false
gitlab_rails['object_store']['connection'] = {
  'provider' => 'AWS',
  'region' => 'miran-gitlab-s3',
  'endpoint' => 'https://gitlab-minio:9009',
  'aws_access_key_id' => 'S3User',
  'aws_secret_access_key' => 'S3Password',
  'path_style' => true
}
gitlab_rails['object_store']['objects']['artifacts']['bucket'] = 'gl-artifacts'
gitlab_rails['object_store']['objects']['external_diffs']['bucket'] = 'gl-external-diffs'
gitlab_rails['object_store']['objects']['lfs']['bucket'] = 'gl-lfs'
gitlab_rails['object_store']['objects']['uploads']['bucket'] = 'gl-uploads'
gitlab_rails['object_store']['objects']['packages']['bucket'] = 'gl-packages'
gitlab_rails['object_store']['objects']['dependency_proxy']['bucket'] = 'gl-dependency-proxy'
gitlab_rails['object_store']['objects']['terraform_state']['bucket'] = 'gl-terraform-state'
gitlab_rails['object_store']['objects']['pages']['bucket'] = 'gl-pages'
gitlab_rails['object_store']['objects']['ci_secure_files']['bucket'] = 'gl-ci-secure-files'
```

Примените конфигурацию:

```bash
docker exec -t single-node-gitlab gitlab-ctl reconfigure
```

Ожидаемое время недоступности — около минуты на обновление конфигурации GitLab. Теперь миграция:

```bash
docker exec -t single-node-gitlab gitlab-rake gitlab:uploads:migrate:all
docker exec -t single-node-gitlab gitlab-rake gitlab:artifacts:migrate
docker exec -t single-node-gitlab gitlab-rake gitlab:lfs:migrate
docker exec -t single-node-gitlab gitlab-rake gitlab:packages:migrate
```

#### Валидация

```bash
# 1. Проверка доступности MinIO
curl -sk https://gitlab-minio:9009/minio/health/live
# → healthy

# 2. Проверка статуса GitLab
docker exec -t single-node-gitlab gitlab-ctl status

# 3. Проверка загрузки нового объекта через WebGUI
# Загрузите артефакт в любой проект и проверьте, что он появился в MinIO

# 4. Проверка миграции LFS
docker exec -t single-node-gitlab gitlab-rake gitlab:lfs:check
```

#### Откат

В случае проблем отключите объектное хранилище:
1. Остановите `single-node-gitlab`.
2. В `gitlab.rb` закомментируйте блок `object_store`.
3. Запустите контейнер. GitLab продолжит использовать локальное хранилище.

#### Особенности работы с MinIO в Docker

- После подключения объектное хранилище работает сразу. Все новые файлы создаются в нем.
- При потере связи с хранилищем GitLab ищет файлы на локальном диске в `/var/opt/gitlab/gitlab-rails/shared` без лишних запросов.
- После миграции LFS объектов откройте всем заинтересованным доступ к `https://gitlab-minio:9009`, так как GitLab раздаёт git LFS именно с него.
- При использовании самоподписанных сертификатов добавьте их на хосте `single-node-gitlab` в `/docker/gitlab/config/trusted-certs`, иначе команды миграции выполняться не будут.
- Не все объекты переезжают автоматически. Проще перенести недостающие вручную либо пошарить `/var/opt/gitlab/gitlab-rails/shared` между Rails-нодами.
- Логи CI `/var/opt/gitlab/gitlab-ci/builds` в объектное хранилище не переезжают. Рекомендуется шарить эту папку и чистить по cron:

```bash
0 0 * * * find /mnt/gitlab-ci-builds/ -depth -mtime +14 -exec rm -rf {} +
```

### Сценарий 4: Внешний Gitaly

Gitaly, сервис разработки команды GitLab — микросервис в системе GitLab, управляющий хранением и обработкой всех Git-репозиториев. Он принимает запросы от веб-интерфейса и других частей платформы через протокол gRPC и выполняет операции с кодом: чтение, запись, поиск.

Миграция на внешний Gitaly — рекомендую сразу на отдельную дисковую подсистему — из GitLab может быть достаточной для нормализации производительности в случаях активной единовременной нагрузки по выкачиванию репозиториев. Например, при массированном запуске тестов в Jenkins/GitLab CI по расписанию, что характеризуется ошибками вида `GitLab error: Gitaly is unreachable` в логе `git clone`.

Gitaly для версий GitLab Enterprise и Community Edition выглядят и ведут себя одинаково. Для Gitaly стоит отдать предпочтение Docker CE образу, так как он занимает меньше места.

#### Подготовка окружения

На хосте `gitlab-gitaly-host` создайте `/docker/docker-compose/docker-compose.yml`:

```yaml
services:
  gitaly:
    image: company-local-docker-images/gitlab/gitlab-ce:19.3.1-ce.0
    container_name: gitlab-gitaly
    logging:
      options:
        max-size: "1g"
        max-file: "5"
    volumes:
      - "/docker/gitlab/config:/etc/gitlab"
      - "/docker/gitlab/data:/var/opt/gitlab"
      - "/docker/gitlab/logs:/var/log/gitlab"
    ports:
      - "8075:8075"
      - "9236:9236"
    restart: unless-stopped
    deploy:
      resources:
        limits:
          cpus: '4'
          memory: 7G
    networks:
      - gitlabnet

networks:
  gitlabnet:
    driver: bridge
```

Запустите и остановите контейнер для создания конфигурационных файлов:

```bash
docker compose -f /docker/docker-compose/docker-compose.yml up -d
docker compose -f /docker/docker-compose/docker-compose.yml down
```

Запретите автоматическое обновление базы:

```bash
touch /docker/gitlab/config/skip-auto-reconfigure
```

Скопируйте секреты с основного хоста:

```bash
scp gitlab.example.com:/docker/gitlab/config/gitlab-secrets.json /docker/gitlab/config/
```

При использовании самоподписанных сертификатов добавьте их в `/docker/gitlab/config/trusted-certs`.

Настройте `/docker/gitlab/config/gitlab.rb` на хосте Gitaly:

```ruby
gitlab_rails['internal_api_url'] = 'https://gitlab.example.com'

# Отключить все сервисы кроме Gitaly
postgresql['enable'] = false
redis['enable'] = false
nginx['enable'] = false
puma['enable'] = false
sidekiq['enable'] = false
gitlab_workhorse['enable'] = false
prometheus_monitoring['enable'] = false
gitlab_kas['enable'] = false

gitaly['enable'] = true
prometheus['enable'] = true

gitlab_rails['auto_migrate'] = false

gitaly['configuration'] = {
  listen_addr: '0.0.0.0:8075',
  prometheus_listen_addr: '0.0.0.0:9236',
  auth: {
    token: 'GITALY_TOKEN',
  },
  storage: [
    {
      name: 'gitaly',
      path: '/var/opt/gitlab/git-data/repositories',
    },
  ]
}
```

Проверьте конфигурацию:

```bash
docker exec -it gitlab-gitaly /opt/gitlab/embedded/bin/gitaly check /var/opt/gitlab/gitaly/config.toml
```

#### Настройка основного GitLab

На хосте `single-node-gitlab` отредактируйте `/docker/gitlab/config/gitlab.rb`:

```ruby
gitaly['enable'] = false
gitlab_rails['repositories_storages'] = {
  "gitaly-external" => {
    "gitaly_address" => "tcp://gitaly-host:8075",
    "gitaly_token" => 'GITALY_TOKEN'
  }
}
```

#### Миграция репозиториев

Планируйте недоступность сервиса.

1. Остановите `single-node-gitlab`.
2. Выполните финальную синхронизацию данных rsync:

```bash
rsync -avhz --delete --exclude='.gitaly-metadata' \
  gitlab.example.com:/docker/gitlab/data/git-data/repositories/ \
  gitlab-gitaly-host:/docker/gitlab/data/git-data/repositories/
```

3. Исправьте права на внешнем Gitaly:

```bash
chown -R git:git /docker/gitlab/data/git-data/repositories/
```

4. Запустите `single-node-gitlab`.

Проверьте успешность через WebGUI: содержимое любого репозитория должно отображаться, изменения должны вноситься. При проблемах проверьте:

```bash
docker exec -it gitlab-gitaly /opt/gitlab/embedded/bin/gitaly check /var/opt/gitlab/gitaly/config.toml
```

Откат выполняется через возврат к предыдущей конфигурации `gitlab.rb`.

#### Валидация

```bash
# 1. Проверка конфигурации Gitaly
docker exec -it gitlab-gitaly /opt/gitlab/embedded/bin/gitaly check /var/opt/gitlab/gitaly/config.toml

# 2. Проверка клонирования репозитория
git clone https://gitlab.example.com/group/project.git /tmp/test-clone
cd /tmp/test-clone && git log --oneline | head

# 3. Проверка статуса GitLab
docker exec -t single-node-gitlab gitlab-ctl status

# 4. Проверка метрик Gitaly
curl -sk https://gitlab-gitaly:9236/metrics | grep gitaly_request_duration_seconds
```

#### Откат

В случае проблем вернитесь к локальному Gitaly:
1. Остановите `single-node-gitlab`.
2. Восстановите исходный `gitlab.rb` из резервной копии.
3. Запустите контейнер.

### Сценарий 5: Внешний Sidekiq

Sidekiq обрабатывает очереди фоновых задач. Масштабирование приносит результат при большой CI/CD нагрузке (одновременный запуск тысяч пайплайнов). Прерывание в обслуживании не требуется.

#### Подготовка окружения

На хосте `gitlab-sidekiq-host` создайте `/docker/docker-compose/docker-compose.yml`:

```yaml
services:
  sidekiq:
    image: company-local-docker-images/gitlab-ce:19.3.1-ce.0
    container_name: gitlab-sidekiq
    hostname: gitlab-sidekiq-host
    logging:
      options:
        max-size: "1g"
        max-file: "5"
    volumes:
      - "/docker/gitlab/config:/etc/gitlab"
      - "/docker/gitlab/data:/var/opt/gitlab"
      - "/docker/gitlab/logs:/var/log/gitlab"
    ports:
      - "8082:8082"
    restart: unless-stopped
    deploy:
      resources:
        limits:
          cpus: '4'
          memory: 15G
    networks:
      - gitlabnet

networks:
  gitlabnet:
    driver: bridge
```

`hostname` — необязательный, но удобный параметр, отвечает за отображение читаемого имени в WebGUI GitLab.

Запустите и остановите контейнер для создания файлов конфигурации:

```bash
docker compose -f /docker/docker-compose/docker-compose.yml up -d
docker compose -f /docker/docker-compose/docker-compose.yml down
```

Запретите автоматическое обновление базы:

```bash
touch /docker/gitlab/config/skip-auto-reconfigure
```

Скопируйте секреты и сертификаты с основного хоста.

#### Конфигурация

На хосте `gitlab-sidekiq-host` отредактируйте `/docker/gitlab/config/gitlab.rb`:

```ruby
external_url 'https://gitlab.example.com'
roles ['sidekiq_role']

gitlab_rails['auto_migrate'] = false

### Object storage
gitlab_rails['object_store']['enabled'] = true
gitlab_rails['object_store']['proxy_download'] = false
gitlab_rails['object_store']['connection'] = {
  'provider' => 'AWS',
  'region' => 'gitlab-s3',
  'endpoint' => 'https://gitlab-minio:9009',
  'aws_access_key_id' => 'S3User',
  'aws_secret_access_key' => 'S3Password',
  'path_style' => true
}
gitlab_rails['object_store']['objects']['artifacts']['bucket'] = 'gl-artifacts'
gitlab_rails['object_store']['objects']['external_diffs']['bucket'] = 'gl-external-diffs'
gitlab_rails['object_store']['objects']['lfs']['bucket'] = 'gl-lfs'
gitlab_rails['object_store']['objects']['uploads']['bucket'] = 'gl-uploads'
gitlab_rails['object_store']['objects']['packages']['bucket'] = 'gl-packages'
gitlab_rails['object_store']['objects']['dependency_proxy']['bucket'] = 'gl-dependency-proxy'
gitlab_rails['object_store']['objects']['terraform_state']['bucket'] = 'gl-terraform-state'
gitlab_rails['object_store']['objects']['pages']['bucket'] = 'gl-pages'
gitlab_rails['object_store']['objects']['ci_secure_files']['bucket'] = 'gl-ci-secure-files'

gitlab_rails['usage_ping_enabled'] = false

### Gitaly
gitaly['enable'] = false
gitlab_rails['repositories_storages'] = {
  "default" => {
    "gitaly_address" => 'tcp://gitlab-gitaly-host:8075',
    "gitaly_token" => 'GITALY_TOKEN'
  }
}

### Database
postgresql['enable'] = false
gitlab_rails['db_adapter'] = "postgresql"
gitlab_rails['db_encoding'] = "unicode"
gitlab_rails['db_database'] = "gitlabhq_production"
gitlab_rails['db_username'] = "gitlab"
gitlab_rails['db_password'] = "DB_PASSWORD"
gitlab_rails['db_host'] = "gitlab-pg-host"
gitlab_rails['db_port'] = 5432

### Redis
redis['enable'] = false
gitlab_rails['redis_port'] = '6379'
gitlab_rails['redis_host'] = 'gitlab-redis-host'
gitlab_rails['redis_password'] = 'REDIS_PASS'

### Sidekiq
sidekiq['listen_address'] = "0.0.0.0"
sidekiq['queue_groups'] = ['*'] * 4
sidekiq['metrics_enabled'] = true
sidekiq['exporter_tls_enabled'] = false
sidekiq['listen_address'] = '0.0.0.0'
sidekiq['listen_port'] = 8082
```

Запустите контейнер:

```bash
docker compose -f /docker/docker-compose/docker-compose.yml up -d
```

Через 5 минут проверьте в WebGUI количество процессов Sidekiq. По умолчанию их должно быть больше 1.

**Важно:** число в `sidekiq['queue_groups'] = ['*'] * 4` должно соответствовать числу доступных CPU. Все дополнительные конфигурации (LDAP, KAS, Pages) обязательно дублируются в настройке Sidekiq.

#### Валидация

```bash
# 1. Проверка статуса Sidekiq
docker exec -t gitlab-sidekiq gitlab-ctl status sidekiq

# 2. Проверка количества процессов Sidekiq
docker exec -t gitlab-sidekiq gitlab-ctl tail sidekiq --since 1m | grep -c "started"

# 3. Проверка очередей
curl -sk https://gitlab.example.com/api/v4/ci/jobs | jq '.[] | .status'

# 4. Проверка здоровья инстанса
docker exec -t single-node-gitlab gitlab-rake gitlab:sidekiq:check
```

#### Откат

В случае проблем вернитесь к встроенному Sidekiq:
1. Остановите `single-node-gitlab`.
2. В `gitlab.rb` закомментируйте блок `sidekiq_role` и добавьте `sidekiq['enable'] = true`.
3. Запустите контейнер.

### Сценарий 6: Rails-ноды и HAProxy

Rails — монолитное приложение, обрабатывающее API и веб-интерфейс. Масштабирование Rails не требует прерывания в обслуживании. Новые ноды добавляются и удаляются на лету через HAProxy.

#### Подготовка окружения для Rails-нод

На каждом хосте `gitlab-rails-(01/02)-host` создайте `/docker/docker-compose/docker-compose.yml`:

```yaml
services:
  gitlab-rails-01:
    image: company-local-docker-images/gitlab-ce:19.3.1-ce.0
    container_name: gitlab-rails-01
    logging:
      options:
        max-size: "1g"
        max-file: "5"
    volumes:
      - "/docker/gitlab/config:/etc/gitlab"
      - "/docker/gitlab/data:/var/opt/gitlab"
      - "/docker/gitlab/logs:/var/log/gitlab"
      - "/network-mnt/gitlab-ci-builds:/var/opt/gitlab/gitlab-ci/builds"
    ports:
      - "22:22"
      - "80:80"
      - "9100:9100"
    restart: unless-stopped
    deploy:
      resources:
        limits:
          cpus: '8'
          memory: 8G
    networks:
      - gitlabnet

networks:
  gitlabnet:
    driver: bridge
```

Запустите и остановите контейнер:

```bash
docker compose -f /docker/docker-compose/docker-compose.yml up -d
docker compose -f /docker/docker-compose/docker-compose.yml down
```

Запретите автоматическое обновление базы:

```bash
touch /docker/gitlab/config/skip-auto-reconfigure
```

Скопируйте `gitlab-secrets.json` и SSH-ключи (`ssh_host_ecdsa_key`, `ssh_host_ecdsa_key.pub`, `ssh_host_ed25519_key`, `ssh_host_ed25519_key.pub`, `ssh_host_rsa_key`, `ssh_host_rsa_key.pub`) с основного хоста. При использовании самопподписанных сертификатов добавьте их в `/docker/gitlab/config/trusted-certs`.

Настройте `/docker/gitlab/config/gitlab.rb`:

```ruby
external_url 'https://gitlab.example.com'
roles ['application_role']

gitlab_rails['auto_migrate'] = false

### Object storage
gitlab_rails['object_store']['enabled'] = true
gitlab_rails['object_store']['proxy_download'] = false
gitlab_rails['object_store']['connection'] = {
  'provider' => 'AWS',
  'region' => 'gitlab-s3',
  'endpoint' => 'https://gitlab-minio:9009',
  'aws_access_key_id' => 'S3User',
  'aws_secret_access_key' => 'S3Password',
  'path_style' => true
}
gitlab_rails['object_store']['objects']['artifacts']['bucket'] = 'gl-artifacts'
gitlab_rails['object_store']['objects']['external_diffs']['bucket'] = 'gl-external-diffs'
gitlab_rails['object_store']['objects']['lfs']['bucket'] = 'gl-lfs'
gitlab_rails['object_store']['objects']['uploads']['bucket'] = 'gl-uploads'
gitlab_rails['object_store']['objects']['packages']['bucket'] = 'gl-packages'
gitlab_rails['object_store']['objects']['dependency_proxy']['bucket'] = 'gl-dependency-proxy'
gitlab_rails['object_store']['objects']['terraform_state']['bucket'] = 'gl-terraform-state'
gitlab_rails['object_store']['objects']['pages']['bucket'] = 'gl-pages'
gitlab_rails['object_store']['objects']['ci_secure_files']['bucket'] = 'gl-ci-secure-files'

gitlab_rails['usage_ping_enabled'] = false

### Gitaly
gitaly['enable'] = false
gitlab_rails['repositories_storages'] = {
  "default" => {
    "gitaly_address" => "tcp://gitlab-gitaly-host:8075",
    "gitaly_token" => 'GITALY_TOKEN'
  }
}

### Database
postgresql['enable'] = false
gitlab_rails['db_adapter'] = "postgresql"
gitlab_rails['db_encoding'] = "unicode"
gitlab_rails['db_database'] = "gitlabhq_production"
gitlab_rails['db_username'] = "gitlab"
gitlab_rails['db_password'] = "DB_PASSWORD"
gitlab_rails['db_host'] = "gitlab-pg-host"
gitlab_rails['db_port'] = 5432

### Redis
redis['enable'] = false
gitlab_rails['redis_port'] = '6379'
gitlab_rails['redis_host'] = 'gitlab-redis-host'
gitlab_rails['redis_password'] = 'REDIS_PASS'

### Sidekiq
sidekiq['enable'] = false

### NGINX
nginx['redirect_http_to_https'] = false
nginx['listen_port'] = 80
nginx['listen_https'] = false

### Logging
logging['svlogd_size'] = 200 * 1024 * 1024
logging['svlogd_num'] = 5
logging['svlogd_timeout'] = 24 * 60 * 60
logging['svlogd_filter'] = "gzip"
logging['logrotate_frequency'] = "daily"
logging['logrotate_size'] = 200 * 1024 * 1024
logging['logrotate_rotate'] = 5
logging['logrotate_compress'] = "compress"

### Prometheus
node_exporter['enable'] = true
node_exporter['listen_address'] = '0.0.0.0:9100'
```

Запустите контейнер и проверьте логи.

#### HAProxy

На хосте с HAProxy размещается ведущий GitLab Rails, выведенный из пользовательской нагрузки. Предварительно переопределите порт 22 для SSH.

Создайте `/docker/docker-compose/docker-compose.yml`:

```yaml
services:
  gitlab-haproxy:
    image: company-local-docker-images/haproxy:3.2.22
    container_name: gitlab-haproxy
    ports:
      - "22:22"
      - "80:80"
      - "443:443"
      - "8404:8404"
    volumes:
      - "/docker/haproxy:/usr/local/etc/haproxy"
      - "/docker/haproxy/stats:/var/lib/haproxy/stats"
      - "/opt/ssl:/opt/ssl"
    restart: unless-stopped
    networks:
      - gitlabnet

  gitlab-rails-main:
    image: company-local-docker-images/gitlab-ce:19.3.1-ce.0
    container_name: gitlab-rails-main
    logging:
      options:
        max-size: "1g"
        max-file: "5"
    volumes:
      - "/docker/gitlab/config:/etc/gitlab"
      - "/docker/gitlab/data:/var/opt/gitlab"
      - "/docker/gitlab/logs:/var/log/gitlab"
      - "/network-mnt/gitlab-ci-builds:/var/opt/gitlab/gitlab-ci/builds"
    restart: unless-stopped
    deploy:
      resources:
        limits:
          cpus: '8'
          memory: 8G
    networks:
      - gitlabnet

networks:
  gitlabnet:
    driver: bridge
```

Создайте файл статистики:

```bash
touch /docker/haproxy/stats/stats.state
```

Конфигурационный файл `/docker/haproxy/haproxy.cfg`:

```cfg
global
    expose-experimental-directives
    stats-file /var/lib/haproxy/stats/stats.state
    log 127.0.0.1:514 local0
    daemon

defaults
    log global
    mode http
    option httplog
    option dontlognull
    option http-server-close
    option redispatch
    timeout http-request 10s
    timeout queue 20s
    timeout connect 5s
    timeout client 20m
    timeout server 20m
    timeout http-keep-alive 10s
    timeout check 10s
    default-server inter 10s fall 3 rise 2
    balance leastconn

frontend stats
    mode http
    bind *:8404 ssl crt /opt/ssl/my.company.ssl.pem
    http-request use-service prometheus-exporter if { path /metrics }
    stats enable
    stats uri /stats
    stats show-modules
    stats refresh 10s

frontend rails-http
    mode http
    bind *:80
    bind *:443 ssl crt /opt/ssl/my.company.ssl.pem
    http-request redirect scheme https code 301 unless { ssl_fc }
    http-response set-header X-Backend-Server %s
    option forwardfor except 127.0.0.0/8
    use_backend rails-http-backend
    option httplog

backend rails-http-backend
    mode http
    server gitlab-rails-01 gitlab-rails-01:80 check
    server gitlab-rails-02 gitlab-rails-02:80 check

frontend rails-ssh
    mode tcp
    bind *:22
    use_backend rails-ssh-backend
    option tcplog

backend rails-ssh-backend
    mode tcp
    server gitlab-rails-01 gitlab-rails-01:22 check
    server gitlab-rails-02 gitlab-rails-02:22 check
```

#### Миграция на HAProxy

1. Запланируйте время недоступности. Сам перезапуск занимает не более минуты, текущие соединения не прерываются.
2. Остановите старый контейнер:

```bash
docker stop single-node-gitlab
```

3. Запустите новый стек:

```bash
docker compose -f /docker/docker-compose/docker-compose.yml up -d
```

4. Проверьте все CRON-задания и перенесите их на новый инстанс при необходимости.

#### Валидация

```bash
# 1. Проверка статуса HAProxy
docker exec -t gitlab-haproxy haproxy -c -f /usr/local/etc/haproxy/haproxy.cfg
# → Configuration file is valid

# 2. Проверка статистики HAProxy
curl -sk https://haproxy-host:8404/stats
# → HTML со статистикой

# 3. Проверка доступности Rails-нод
curl -sk https://gitlab.example.com/-/readiness
# → {"status":"ok"}

# 4. Проверка балансировки
for i in {1..10}; do curl -sk https://gitlab.example.com/-/readiness | grep backend; done
# → Должны быть ответы с обеих нод
```

#### Откат

В случае проблем вернитесь к одноконтейнерной архитектуре:
1. Остановите стек HAProxy: `docker compose -f /docker/haproxy/docker-compose.yml down`.
2. Запустите исходный `single-node-gitlab`.
3. Обновите DNS/прокси чтобы указывать на старый инстанс.

## Ограничения и крайние случаи

### Миграция без прерывания обслуживания

Технически перенести данные PostgreSQL без прерывания обслуживания можно через логическую репликацию или `pg_dump` с последующим `pg_restore` во время работы. Однако риск потери новых записей, созданных в момент копирования и переключения, слишком высок для production. Поэтому миграция PostgreSQL и Gitaly всегда требует запланированного времени недоступности.

### Совместимость версий PostgreSQL

- GitLab 19.x работает только с PostgreSQL 17.
- При обновлении с GitLab 18.x, где использовался PostgreSQL 16, выполните миграцию БД до обновления GitLab.
- `pg_dump` версии 16 несовместим с PostgreSQL 17. Убедитесь, что инструменты на стороне источника соответствуют целевой версии.

### Совместимость Redis/Valkey

- GitLab 19.x поддерживает Valkey 7.2+ и Redis 7.2+.
- Redis 6 не поддерживается с GitLab 19.0.
- При миграции с Redis 6 на Valkey 7.2+ данные автоматически переносятся благодаря совместимому протоколу.

### Производительность дисков Gitaly

Gitaly критичен к задержкам диска. При использовании HDD или сетевых хранилищ с высокой задержкой (>10ms) возникают таймауты при массовом клонировании. Используйте NVMe с IOPS > 3000.

### Самоподписанные сертификаты

При использовании самоподписанных сертификатов добавьте их в `/docker/gitlab/config/trusted-certs` на всех нодах перед миграцией. Иначе команды миграции (`gitlab-rake gitlab:lfs:migrate` и аналогичные) завершатся с ошибкой SSL.

### Логи CI

Логи CI `/var/opt/gitlab/gitlab-ci/builds` не мигрируют в MinIO автоматически. Рекомендуется настроить шару между Rails-нодами и периодическую очистку:

```bash
0 0 * * * find /mnt/gitlab-ci-builds/ -depth -mtime +14 -exec rm -rf {} +
```

### Обновление отдельных компонентов

Отдельные контейнеры можно обновлять быстрее, чем выходит новый релиз GitLab. Это ускоряет устранение уязвимостей, но требует тестирования совместимости перед обновлением production.

## Устранение неполадок

### Типичные ошибки

| Ошибка | Компонент | Причина | Решение |
| :--- | :--- | :--- | :--- |
| 500 после переключения на PostgreSQL | PostgreSQL | Несовместимость версий pg_dump | Убедитесь, что версия pg_dump соответствует целевой версии PostgreSQL |
| 500 после переключения на Redis/Valkey | Redis/Valkey | Неверный пароль или хост | Проверьте `gitlab_rails['redis_password']` и доступность порта 6379 |
| 502/504 | Puma | Недостаток shared memory | Увеличьте `shm_size` до 1GB |
| `Gitaly is unreachable` | Gitaly | Проблемы с диском или сетью | Проверьте I/O (`iostat -x 1`) и сетевую доступность порта 8075 |
| Пропал создание runners | PostgreSQL | Часовой пояс не UTC | Не монтируйте `/etc/localtime`, используйте UTC |
| Очереди Sidekiq растут | Sidekiq | Недостаточная параллельность или блокировки в БД | Увеличьте `sidekiq['queue_groups']`, проверьте долгие запросы |
| Миграция LFS не проходит | MinIO | Самоподписанный сертификат | Добавьте сертификат в `trusted-certs` |

### Диагностика

```bash
# Статус компонентов
docker exec -it gitlab-<component> gitlab-ctl status

# Логи конкретного компонента
docker exec -it gitlab-<component> gitlab-ctl tail <service>

# Проверка конфигурации Gitaly
docker exec -it gitlab-gitaly /opt/gitlab/embedded/bin/gitaly check /var/opt/gitlab/gitaly/config.toml

# Подключение к PostgreSQL
docker exec -it gitlab-pg psql -U gitlab -d gitlabhq_production -c "SELECT version();"

# Проверка Redis/Valkey
docker exec -it gitlab-redis valkey-cli -a REDIS_PASS ping

# Health-check GitLab
curl -sk https://gitlab.example.com/-/health
# → {"healthy":true}
```

## Лучшие практики

1. **Shared memory:** всегда устанавливайте `shm_size: 1g` для контейнеров GitLab. Стандартных 64MB недостаточно для Puma и системы метрик.
2. **CPU для Ruby:** количество CPU для Puma и Sidekiq должно быть степенью двойки (2, 4, 8, 16).
3. **Диски для Gitaly:** используйте NVMe. Gitaly критичен к задержкам диска; HDD или сетевые хранилища с высокой задержкой приводят к таймаутам.
4. **Отдельный ведущий Rails:** один инстанс остается для обновлений и бэкапов, выводится из пользовательской нагрузки за HAProxy.
5. **Время недоступности:** планируйте прерывание только для миграции PostgreSQL и Gitaly. Redis и MinIO переключаются без даунтайма.
6. **Самоподписанные сертификаты:** всегда добавляйте их в `trusted-certs` на всех нодах перед миграцией.
7. **Бэкап перед миграцией:** создайте полный бэкап `gitlab-backup create` и скопируйте `gitlab-secrets.json` на безопасное хранилище.
8. **Откат:** тестируйте откат на staging перед миграцией продукта. Миграция откатывается возвратом предыдущей конфигурации `gitlab.rb`.
9. **Мониторинг:** подключайте экспортеров Prometheus для PostgreSQL, Redis, Gitaly, Sidekiq и Rails-нод.
10. **CI-логи:** логи сборок `/var/opt/gitlab/gitlab-ci/builds` не мигрируют в MinIO автоматически. Настройте шару и cron-очистку.

## Управление изменениями и RTO/RPO

### Change Management

Миграция на кластер — это изменение production-инфраструктуры, требующее формального Change Management:

1. **Создание maintenance window** — уведомите пользователей за 24 часа, запланируйте в нерабочее время.
2. **Бэкап** — создайте полный бэкап `gitlab-backup create` и скопируйте `gitlab-secrets.json` на безопасное хранилище.
3. **Тестирование отката** — выполните миграцию на staging перед production.
4. **Документирование** — зафиксируйте все изменения в конфигурации и топологии.

### RTO/RPO

| Сценарий | RTO | RPO |
|:---|:---|:---|
| Миграция PostgreSQL | 10–30 минут | Минуты (требуется maintenance mode) |
| Миграция Redis/Valkey | ~1 минута | Секунды (очереди сбрасываются) |
| Миграция MinIO | ~1 минута | Минуты (новые объекты) |
| Миграция Gitaly | 10–30 минут | Минуты (требуется остановка записей) |
| Миграция Sidekiq | ~1 минута | Секунды (задачи перезапускаются) |
| Миграция Rails | ~1 минута | Секунды (stateless) |

## Дополнительная информация

### Связанные файлы базы знаний

- **[Архитектура и масштабирование GitLab](../Concepts/gitlab_platform_architecture.md)** — теория компонентов и варианты развертывания.
- **[Установка Self-Hosted GitLab CE с помощью Docker](../Tutorials/self_hosted_installation.md)** — одноузловая установка.
- **[Регистрация GitLab Runner](./runner_registration.md)** — настройка CI/CD после миграции.
- **[GitLab + Runner через Docker Compose](../Tutorials/gitlab_runner_docker_compose.md)** — готовый стек для быстрого старта.

### Важные замечания

- **Gitaly Cluster (RAFT):** в GitLab 19.x кластеризация Gitaly через RAFT не поддерживается в Docker. Используется только на виртуальных машинах.
- **PostgreSQL 17:** начиная с GitLab 19.0, минимальная версия PostgreSQL — 17. При планировании обновления подготовьте миграцию БД заранее.
- **Valkey:** начиная с GitLab 19.0, поддержка Redis 6 удалена. Для новых инсталляций используйте Valkey 7.2+ или Redis 7.2+.
- **Обновление компонентов:** отдельные контейнеры можно обновлять быстрее, чем выходит новый релиз GitLab, что ускоряет устранение уязвимостей информационной безопасности.
