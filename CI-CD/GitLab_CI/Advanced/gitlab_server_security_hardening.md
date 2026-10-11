# Безопасность и закрепление GitLab Server

**Актуально для:** GitLab 17.x–19.x (Omnibus, Docker, Helm)

## Определения

* **Server Hardening (Закрепление сервера)** — процесс уменьшения поверхности атаки GitLab инстанса через настройку ОС, сетевых политик, прав доступа, конфигурации компонентов и управления инцидентами.
* **Instance-level Security** — защита на уровне всего GitLab инстанса (в отличие от project-level security).
* **Defense in Depth** — многоуровневая защита (сеть, ОС, приложение, данные, мониторинг).
* **Least Privilege** — принцип предоставления минимально необходимых прав каждому компоненту, пользователю и сервису.
* **Fail Secure** — при сбое система остаётся в безопасном состоянии (например, отказ в доступе вместо открытия доступа).
* **RBAC (Role-Based Access Control)** — разграничение прав доступа на основе ролей.
* **SELinux/AppArmor** — механизмы мандатного контроля доступа (MAC) в Linux.
* **MFA (Multi-Factor Authentication)** — многофакторная аутентификация; обязательна для администраторов.
* **SSO (Single Sign-On)** — централизованная аутентификация через LDAP/SAML/OIDC; снижает риск утечек паролей.
* **Audit Event** — событие безопасности, фиксирующее критичное действие (логин, изменение роли, удаление проекта).
* **SIEM (Security Information and Event Management)** — система централизованного сбора и корреляции логов безопасности.
* **Incident Response** — набор процедур для реагирования на компрометацию инстанса.
* **Vulnerability Management** — процесс отслеживания, оценки и устранения уязвимостей в компонентах GitLab.
* **Patching SLA** — соглашение о времени установки обновлений безопасности; критичные уязвимости требуют SLA ≤ 7 дней.
* **Immutable Infrastructure** — использование golden images и запрет прямых изменений на production-хостах.
* **Separation of Duties** — разделение ответственности между администраторами (разработка, утверждение, deployment).
* **WORM (Write Once, Read Many)** — хранилище, защищённое от изменений и удаления; используется для бэкапов и audit logs.
* **RTO/RPO** — Recovery Time Objective (максимальное время простоя) и Recovery Point Objective (максимальная потеря данных).
* **DR Drill (Тренировка восстановления)** — плановое упражнение по восстановлению инстанса из бэкапа в изолированной среде.
* **HashiCorp Vault** — система управления секретами; может использоваться для хранения `gitlab-secrets.json` или внешних секретов CI/CD.

## Основные концепции

### Модель угроз GitLab Server

GitLab инстанс сталкивается с несколькими категориями угроз:

1. **Неавторизованный доступ** — brute-force атаки на веб-интерфейс, SSH, API.
2. **Утечка данных** — компрометация базы данных, репозиториев, секретов, артефактов.
3. **Отказ в обслуживании (DoS)** — исчерпание ресурсов (CPU, память, диск, сеть).
4. **Инъекции** — SQL-инъекции, command injection через CI/CD пайплайны, template injection.
5. **Компрометация Runner'ов** — доступ к секретам через скомпрометированные раннеры.
6. **Внутренняя угроза** — злоупотребление правами администратора, несанкционированные изменения.
7. **Supply Chain Attack** — компрометация зависимостей, артефактов, Docker-образов.
8. **Compromised Secrets** — утечка `gitlab-secrets.json`, токенов, паролей БД.

### Принципы закрепления

| Принцип | Описание |
|:---|:---|
| **Least Privilege** | Минимальные права для каждого компонента, пользователя и сервиса |
| **Defense in Depth** | Несколько слоёв защиты (сеть, ОС, приложение, данные, мониторинг) |
| **Fail Secure** | При сбое система остаётся в безопасном состоянии |
| **Audit Everything** | Ведение логов всех критичных операций с защитой от изменений |
| **Separation of Duties** | Разделение ответственности между администраторами |
| **Immutable Infrastructure** | Использование golden images, запрет прямых изменений на production |
| **Patch Management** | Своевременное обновление компонентов согласно SLA |
| **Zero Trust** | Никому не доверять по умолчанию; проверка каждой попытки доступа |

### Уровни защиты GitLab Server

| Уровень | Компонент | Меры защиты |
|:---|:---|:---|
| **Сеть** | Firewall, VLAN, VPN | Segregation, whitelist, rate limiting |
| **ОС** | Linux host | SELinux/AppArmor, sysctl, fail2ban, SSH hardening |
| **GitLab** | Rails, Nginx, Sidekiq | SSL/TLS, rate limiting, auth, RBAC |
| **База данных** | PostgreSQL, Valkey/Redis | Encryption at rest, auth, network isolation |
| **Хранилище** | Gitaly, LFS, артефакты | Encryption at rest, access control |
| **Runner'ы** | Docker, Kubernetes, VM | Isolation, least privilege, ephemeral |
| **Мониторинг** | Логи, метрики, алерты | SIEM, audit events, anomaly detection |

### Слои GitLab Server и точки закрепления

GitLab состоит из нескольких компонентов, каждый из которых требует отдельной настройки безопасности:

1. **Nginx** — reverse proxy, SSL/TLS termination, rate limiting, HTTP security headers.
2. **Rails (Puma)** — основное приложение; сессии, CSRF, password hashing (bcrypt/argon2).
3. **Sidekiq** — очередь фоновых задач; изоляция очередей, ограничение concurrency.
4. **PostgreSQL** — база данных; encryption at rest, auth, network isolation, WAL encryption.
5. **Valkey/Redis** — кэш и брокер сообщений; auth, maxmemory policy, network isolation.
6. **Gitaly** — сервис доступа к Git-репозиториям; network isolation, TLS, auth.
7. **GitLab Shell** — SSH-доступ к репозиториям; ограничение команд, chroot.
8. **Object Storage** — S3/MinIO/GCS/Azure для артефактов, LFS, uploads; encryption, bucket policies.

## Практические сценарии

### Предварительные требования

**Аппаратные требования:**
- GitLab Server: 4 CPU, 8 ГБ RAM, 50 ГБ SSD (минимум для small team)
- Диски: SSD/NVMe с IOPS > 3000 для PostgreSQL и Gitaly
- Сеть: latency между Rails и Gitaly < 2 ms; изолированные подсети для management, application, database, storage

**Программные требования:**
- ОС: Rocky Linux 9, AlmaLinux 9, Ubuntu 22.04/24.04 LTS с systemd
- PostgreSQL: 15+ (GitLab 18.x), 17+ (GitLab 19.x)
- Valkey/Redis: Valkey 7.2+ или Redis 7.2+
- NTP: синхронизация времени на всех узлах (разница < 100 ms)

**Инициализация:**
1. Обновите ОС до последних патчей безопасности.
2. Настройте firewall и fail2ban.
3. Создайте отдельного пользователя `git` с ограниченными правами.
4. Настройте SSH hardening (ключи, отключение root login, MFA).
5. Подготовьте `gitlab-secrets.json` с сильными случайными ключами.
6. Настройте внешний URL и SSL/TLS.
7. Настройте PostgreSQL, Valkey/Redis, Gitaly с security-параметрами.

### Сценарий 1: Закрепление ОС (Ubuntu/Debian/RHEL-совместимые)

```bash
# 1. Обновление системы и установка security-патчей
sudo apt update && sudo apt upgrade -y && sudo apt autoremove -y
# Для RHEL-совместимых:
# sudo dnf update --security && sudo dnf clean all

# 2. Установка и настройка fail2ban
sudo apt install fail2ban -y

# /etc/fail2ban/jail.local
[sshd]
enabled = true
port = 22
filter = sshd
logpath = /var/log/auth.log
maxretry = 3
bantime = 3600
findtime = 600

[gitlab-http]
enabled = true
port = http,https
filter = gitlab
logpath = /var/log/gitlab/nginx/gitlab_access.log
maxretry = 10
bantime = 3600
findtime = 600

# 3. Настройка firewall
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow ssh
sudo ufw allow http
sudo ufw allow https
sudo ufw enable

# 4. Настройка sysctl
sudo tee /etc/sysctl.d/99-gitlab-hardening.conf <<EOF
# Отключение IP forwarding (если не используется)
net.ipv4.ip_forward = 0

# Защита от SYN flood
net.ipv4.tcp_syncookies = 1
net.ipv4.tcp_synack_retries = 2

# Отключение source routing
net.ipv4.conf.all.accept_source_route = 0
net.ipv4.conf.default.accept_source_route = 0

# Защита от ICMP redirect
net.ipv4.conf.all.accept_redirects = 0
net.ipv4.conf.default.accept_redirects = 0

# Логирование подозрительных пакетов
net.ipv4.conf.all.log_martians = 1

# Защита от IP spoofing
net.ipv4.conf.all.rp_filter = 1
net.ipv4.conf.default.rp_filter = 1
EOF
sudo sysctl -p /etc/sysctl.d/99-gitlab-hardening.conf

# 5. Ограничение ресурсов через systemd (резервный вариант, если нет cgroups)
sudo mkdir -p /etc/systemd/system/gitlab-runsvdir.service.d
sudo tee /etc/systemd/system/gitlab-runsvdir.service.d/hardening.conf <<EOF
[Service]
LimitNOFILE=65536
LimitNPROC=65536
EOF
sudo systemctl daemon-reload
```

**Валидация:**
```bash
# Проверка: firewall активен
sudo ufw status
# → Status: active

# Проверка: sysctl применён
sysctl net.ipv4.ip_forward
# → net.ipv4.ip_forward = 0

# Проверка: fail2ban запущен
sudo systemctl status fail2ban
# → active (running)
```

### Сценарий 2: Настройка SSH

```bash
# /etc/ssh/sshd_config
Port 2222
PermitRootLogin no
PasswordAuthentication no
PubkeyAuthentication yes
PermitEmptyPasswords no
X11Forwarding no
AllowUsers git
ClientAliveInterval 300
ClientAliveCountMax 2
MaxAuthTries 3
Protocol 2

# Перезапуск SSH
sudo systemctl restart sshd
```

**Валидация:**
```bash
# Проверка: root login запрещён
ssh -o PasswordAuthentication=no root@gitlab.example.com
# → Permission denied (publickey,password)

# Проверка: MFA для пользователя git
sudo ssh-keygen -y -f /home/git/.ssh/id_ed25519
# → публичный ключ совпадает с настроенным
```

### Сценарий 3: Настройка GitLab с security-параметрами

```ruby
# /etc/gitlab/gitlab.rb

# Внешний URL
external_url 'https://gitlab.example.com'

# Отключение ненужных функций
gitlab_rails['packages_enabled'] = true  # Включено по умолчанию
gitlab_rails['container_registry_enabled'] = true
gitlab_rails['dependency_proxy_enabled'] = true

# Ограничение доступа к gitlab-shell
gitlab_rails['gitlab_shell_ssh_port'] = 2222

# Ограничение размера запросов
nginx['client_max_body_size'] = '50m'
nginx['client_body_buffer_size'] = '128k'

# Rate limiting для API
nginx['limit_req_zone'] = "$binary_remote_addr zone=api:10m rate=10r/s"
nginx['limit_req_zone'] = "$binary_remote_addr zone=login:10m rate=1r/s"

# Ограничение соединений
nginx['limit_conn_zone'] = "$binary_remote_addr zone=addr:10m"
nginx['limit_conn'] = "addr 10"

# Таймауты
nginx['keepalive_timeout'] = 65
nginx['client_body_timeout'] = 12
nginx['client_header_timeout'] = 12
nginx['send_timeout'] = 10

# Security headers
nginx['headers'] = {
  'X-Frame-Options' => 'DENY',
  'X-Content-Type-Options' => 'nosniff',
  'X-XSS-Protection' => '1; mode=block',
  'Strict-Transport-Security' => 'max-age=63072000; includeSubDomains; preload',
  'Referrer-Policy' => 'strict-origin-when-cross-origin',
  'Content-Security-Policy' => "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline'"
}

# Ограничение Sidekiq
sidekiq['max_concurrency'] = 20
sidekiq['min_concurrency'] = 5

# Ограничение Puma
puma['worker_processes'] = 4

# Применение
sudo gitlab-ctl reconfigure
```

**Валидация:**
```bash
# Проверка: headers присутствуют
curl -I https://gitlab.example.com | grep -E "X-Frame-Options|X-Content-Type-Options|Strict-Transport-Security"
# → X-Frame-Options: DENY
# → X-Content-Type-Options: nosniff
# → Strict-Transport-Security: max-age=63072000; includeSubDomains; preload

# Проверка: rate limiting работает
ab -n 1000 -c 50 https://gitlab.example.com/users/sign_in
# → После 10 запросов/с с одного IP начинают возвращаться 503
```

### Сценарий 4: Настройка SSL/TLS

```ruby
# /etc/gitlab/gitlab.rb

external_url 'https://gitlab.example.com'

nginx['redirect_http_to_https'] = true
nginx['ssl_certificate'] = "/etc/gitlab/ssl/gitlab.example.com.crt"
nginx['ssl_certificate_key'] = "/etc/gitlab/ssl/gitlab.example.com.key"
nginx['ssl_protocols'] = "TLSv1.2 TLSv1.3"
nginx['ssl_ciphers'] = "ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384"
nginx['ssl_prefer_server_ciphers'] = "off"
nginx['ssl_session_cache'] = "shared:SSL:10m"
nginx['ssl_session_timeout'] = "10m"

# OCSP Stapling
nginx['ssl_stapling'] = true
nginx['ssl_stapling_verify'] = true

# Применение
sudo gitlab-ctl reconfigure
```

**Валидация:**
```bash
# Проверка: TLS 1.0/1.1 отключены
openssl s_client -connect gitlab.example.com:443 -tls1_1
# → handshake failure

# Проверка: OCSP stapling работает
openssl s_client -connect gitlab.example.com:443 -status
# → OCSP response status: successful
```

### Сценарий 5: Защита API и Rate Limiting

```ruby
# /etc/gitlab/gitlab.rb

# Rate limiting для API (GitLab 17.x+)
gitlab_rails['rate_limiting_response_text'] = 'Rate limit exceeded'
gitlab_rails['rate_limits'] = {
  'authenticated_api' => {
    'max_requests' => 600,
    'period' => 1.minute
  },
  'unauthenticated_api' => {
    'max_requests' => 100,
    'period' => 1.minute
  },
  'authenticated_web' => {
    'max_requests' => 300,
    'period' => 1.minute
  },
  'unauthenticated_web' => {
    'max_requests' => 60,
    'period' => 1.minute
  }
}

# Ограничение времени запросов
gitlab_rails['max_request_duration'] = 60
gitlab_rails['gitlab_shell_git_timeout'] = 10

# Отключение ненужных endpoint'ов (если не используются)
gitlab_rails['gitlab_relative_url_root'] = '/'
gitlab_rails['gitlab_shell_ssh_port'] = 2222
```

**Валидация:**
```bash
# Проверка: rate limiting для API
for i in {1..20}; do curl -s -o /dev/null -w "%{http_code}\n" https://gitlab.example.com/api/v4/version; done
# → После 10 запросов начинают возвращаться 429

# Проверка: длинные запросы завершаются
timeout 120 curl -s https://gitlab.example.com/api/v4/projects | head -1
# → таймаут или корректный JSON
```

### Сценарий 6: Безопасность Runner'ов

```toml
# /etc/gitlab-runner/config.toml

concurrent = 10
check_interval = 3

[[runners]]
  name = "production-runner"
  url = "https://gitlab.example.com/"
  token = "xxxxxxxx"
  executor = "docker"
  [runners.docker]
    image = "alpine:latest"
    privileged = false
    disable_cache = false
    shm_size = 0
    # Безопасные опции
    security_opt = ["no-new-privileges:true"]
    cap_drop = ["ALL"]
    cap_add = ["NET_ADMIN"]  # Только если необходимо
    volumes = ["/cache"]
    network_mode = "bridge"
    network_disabled = false
    # Ограничения ресурсов
    memory = "4g"
    cpus = "2"
```

**Валидация:**
```bash
# Проверка: Runner зарегистрирован
gitlab-runner verify
# → Runner=... verified

# Проверка: privileged=false
gitlab-runner list
# → Поле Privileged должно быть false
```

> **Примечание:** Для CI/CD-специфичных сценариев hardening Runner'ов (ephemeral runners, read-only rootfs, network policies) см. **[CI/CD Security Hardening](./cicd_security_hardening.md)**.

### Сценарий 7: Защита от брутфорса

```bash
# Настройка fail2ban для GitLab
sudo tee /etc/fail2ban/filter.d/gitlab.conf <<EOF
[Definition]
failregex = ^<HOST> -.*"(GET|POST).*HTTP/1\.[01]" 404 .*$
            ^<HOST> -.*"(GET|POST).*HTTP/1\.[01]" 401 .*$
            ^<HOST> -.*Failed password for .* from <HOST> port \d+$
            ^<HOST> -.*Invalid user .* from <HOST> port \d+$
ignoreregex =
EOF

sudo tee /etc/fail2ban/jail.d/gitlab.conf <<EOF
[gitlab-http]
enabled = true
port = http,https
filter = gitlab
logpath = /var/log/gitlab/nginx/gitlab_access.log
maxretry = 5
bantime = 3600
findtime = 600
EOF

sudo systemctl restart fail2ban
```

**Валидация:**
```bash
# Проверка: fail2ban активен
sudo fail2ban-client status
# → Status: Jails list: sshd, gitlab-http

# Проверка: забаненный IP
sudo fail2ban-client get gitlab-http banned
# → список IP
```

### Сценарий 8: Безопасность базы данных (обзор)

Безопасность базы данных подробно описана в **[Управление базами данных GitLab](./gitlab_database_management.md)**. Ниже — ключевые checkpoints для hardening:

```ruby
# /etc/gitlab/gitlab.rb

# PostgreSQL: слушать только на localhost
postgresql['listen_address'] = '127.0.0.1'
postgresql['port'] = 5432

# PostgreSQL: включить логирование
postgresql['log_statement'] = 'ddl'
postgresql['log_min_duration_statement'] = 1000
postgresql['log_directory'] = '/var/log/gitlab/postgresql'

# PostgreSQL: encryption at rest (требует LUKS на уровне диска)
postgresql['ssl'] = 'on'
postgresql['ssl_cert'] = '/etc/gitlab/ssl/postgresql.crt'
postgresql['ssl_key'] = '/etc/gitlab/ssl/postgresql.key'

# Valkey/Redis: пароль и network isolation
redis['listen_address'] = '127.0.0.1'
redis['port'] = 6379
redis['requirepass'] = 'strong_password_here'
redis['maxmemory'] = "8gb"
redis['maxmemory_policy'] = "allkeys-lru"

# Применение
sudo gitlab-ctl reconfigure
```

**Валидация:**
```bash
# Проверка: PostgreSQL слушает только localhost
sudo ss -tlnp | grep 5432
# → 127.0.0.1:5432

# Проверка: Valkey/Redis требует пароль
redis-cli -h 127.0.0.1 -p 6379 ping
# → NOAUTH Authentication required.
```

### Сценарий 9: Безопасность Gitaly

```ruby
# /etc/gitlab/gitlab.rb

# Gitaly: слушать только на localhost
gitaly['listen_addr'] = '127.0.0.1:8075'
gitaly['prometheus_listen_addr'] = '127.0.0.1:9236'

# Gitaly: TLS для remote-установок
gitaly['tls_listen_addr'] = '0.0.0.0:8076'
gitaly['certificate_path'] = '/etc/gitlab/ssl/gitaly.crt'
gitaly['key_path'] = '/etc/gitlab/ssl/gitaly.key'

# Gitaly: ограничение ресурсов
gitaly['concurrency'] = 20
gitaly['graceful_restart_timeout'] = '5m'

# Применение
sudo gitlab-ctl reconfigure
```

**Валидация:**
```bash
# Проверка: Gitaly слушает на localhost
sudo ss -tlnp | grep 8075
# → 127.0.0.1:8075

# Проверка: Gitaly health check
gitlab-rake gitlab:gitaly:check
# → OK
```

### Сценарий 10: Управление секретами и Vault

```ruby
# /etc/gitlab/gitlab.rb

# Интеграция с HashiCorp Vault (требуется GitLab 17.10+)
gitlab_rails['vault_server'] = {
  'url' => 'https://vault.example.com',
  'token' => 's.XXXXXXXX',
  'auth_path' => 'gitlab',
  'namespace' => 'admin'
}

# Или: использование Vault для хранения CI/CD секретов
# (через External Secrets Operator в Kubernetes или vault-cli в Omnibus)
```

**Валидация:**
```bash
# Проверка: Vault доступен из GitLab
sudo gitlab-rake gitlab:check SANITIZE=true
# → Vault connection: OK

# Проверка: секреты доступны через Vault backend
sudo gitlab-rails console
> ::Settings.oss.send(:build_settings).dig(:vault, :enabled)
# → true
```

### Сценарий 11: Монторинг и алертинг безопасности

```yaml
# Prometheus alert rules для безопасности
groups:
  - name: gitlab.security
    rules:
      - alert: GitLabFailedLoginRate
        expr: sum(rate(gitlab_rails_failed_login_attempts_total[5m])) > 10
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Высокий rate неудачных логинов"
          
      - alert: GitLabRateLimitExceeded
        expr: increase(gitlab_rails_rate_limiter_total[5m]) > 100
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Rate limit превышен"
          
      - alert: GitLabSidekiqQueueHigh
        expr: gitlab_sidekiq_queue_size_total > 1000
        for: 10m
        labels:
          severity: critical
        annotations:
          summary: "Очередь Sidekiq критична"
```

**Валидация:**
```bash
# Проверка: метрики доступны
curl -s http://gitlab.example.com:8080/-/metrics | grep gitlab_rails_failed_login
# → gitlab_rails_failed_login_attempts_total{...}
```

### Сценарий 12: Incident Response — реагирование на компрометацию

```bash
# 1. Изоляция инстанса (если требуется)
sudo gitlab-ctl stop nginx
# → Входящие запросы отклоняются

# 2. Переключение в maintenance mode
sudo gitlab-rake gitlab:maintenance:on
# → Инстанс переходит в режим обслуживания

# 3. Сбор артефактов для расследования
sudo tar -czf /tmp/gitlab-security-evidence-$(date +%Y%m%d).tar.gz \
  /var/log/gitlab/ \
  /var/opt/gitlab/gitlab-rails/production.log \
  /var/opt/gitlab/postgresql/data/pg_log/ \
  /etc/gitlab/gitlab.rb \
  /etc/gitlab/gitlab-secrets.json

# 4. Ротация всех секретов
sudo gitlab-rake gitlab:secrets:rotate

# 5. Принудительный logout всех пользователей
sudo gitlab-rake gitlab:sessions:clear

# 6. Проверка целостности БД
sudo gitlab-rake gitlab:check SANITIZE=true
sudo gitlab-ctl pg-backup /backup/postgresql-$(date +%Y%m%d).sql.gz

# 7. Восстановление после инцидента
sudo gitlab-ctl restart nginx
sudo gitlab-rake gitlab:maintenance:off
```

**Валидация:**
```bash
# Проверка: режим обслуживания активен
curl -s https://gitlab.example.com/
# → 503 Service Unavailable

# Проверка: все сессии очищены
sudo gitlab-rails console
> Session.count
# → 0
```

## Операции и команды

### Проверка безопасности

```bash
# Комплексная проверка безопасности GitLab
sudo gitlab-rake gitlab:check SANITIZE=true

# Проверка уязвимостей (если установлен bundle-audit)
sudo gitlab-ctl run-bundle-audit

# Проверка открытых портов
sudo ss -tlnp | grep -E '80|443|2222|22|8075|5432|6379'

# Проверка файлов секретов
sudo gitlab-ctl show-secrets

# Проверка прав доступа к конфигурации
ls -la /etc/gitlab/
# gitlab.rb должен быть owned root:root с правами 600
# gitlab-secrets.json должен быть owned root:root с правами 600

# Проверка статуса компонентов
sudo gitlab-ctl status
# → run: gitlab-workhorse, puma, sidekiq, nginx, postgresql, redis, gitaly
```

### Аудит действий

```bash
# Просмотр аудит-логов GitLab
sudo gitlab-ctl tail gitlab-rails/production.log | grep -i audit

# Просмотр логов SSH
sudo grep 'Accepted publickey' /var/log/auth.log

# Просмотр логов fail2ban
sudo fail2ban-client status
sudo fail2ban-client status sshd
sudo fail2ban-client status gitlab-http
```

### Ротация секретов

```bash
# Ротация секретов (требует downtime)
sudo gitlab-rake gitlab:secrets:rotate

# После ротации:
# 1. Обновить все интеграции, использующие старые секреты
# 2. Проверить CI/CD пайплайны
# 3. Проверить интеграции с внешними системами
```

### Бэкап секретов

```bash
# Бэкап gitlab-secrets.json
sudo cp /etc/gitlab/gitlab-secrets.json /backup/gitlab-secrets-$(date +%Y%m%d).json

# Шифрование бэкапа
gpg --symmetric --cipher-algo AES256 /backup/gitlab-secrets-$(date +%Y%m%d).json
```

### Управление обновлениями

```bash
# Проверка доступных обновлений
sudo apt list --upgradable
# Для RHEL-совместимых:
# sudo dnf check-update --security

# Применение только security-патчей (Debian/Ubuntu)
sudo apt upgrade --only-upgrade -y --fix-missing

# Плановое обновление GitLab (Omnibus)
sudo apt install gitlab-ee=19.0.0-ee.0
sudo gitlab-ctl reconfigure
sudo gitlab-rake db:migrate
sudo gitlab-ctl restart

# Проверка версии после обновления
sudo gitlab-rake gitlab:env:info | grep "Current Version"
```

## Валидация и проверка

Перед внесением изменений в production выполните проверки:

1. **ОС:** Проверьте установленные security-патчи (`uname -a`, `apt list --upgradable`); убедитесь в наличии только необходимых сервисов.
2. **Firewall:** Проверьте активные правила (`ufw status`/`iptables -L`); убедитесь, что только порты 80, 443, 2222 открыты.
3. **SSH:** Проверьте доступность только по ключу; root login отключён; порт изменён с 22.
4. **SSL/TLS:** Проверьте протоколы и шифры (`openssl s_client`); HSTS включён; OCSP stapling работает.
5. **Rate Limiting:** Проверьте лимиты API (`ab`/`hey`); убедитесь, что DoS-защита активна.
6. **База данных:** Проверьте слушающие адреса PostgreSQL/Valkey (`ss -tlnp | grep 5432`); убедитесь в отсутствии внешнего доступа к БД.
7. **Gitaly:** Проверьте слушающие адреса Gitaly (`ss -tlnp | grep 8075`); убедитесь в TLS для remote-установок.
8. **Runner'ы:** Проверьте `privileged=false`, `cap_drop=ALL`, отсутствие volume mounts на хост-файлы.
9. **Секреты:** Проверьте права на `gitlab-secrets.json` (`chmod 600`, owned root:root); ротация секретов по графику.
10. **Логи:** Проверьте централизованный сбор логов (ELK/Loki); убедитесь в защите audit logs от изменений.

## Типичные ошибки и решения

| Симптом | Причина | Решение |
|:---|:---|:---|
| `401 Unauthorized` на API | Неверный или просроченный токен | Проверьте Deploy Token, PAT или CI_JOB_TOKEN |
| `403 Forbidden` | Токен без нужного scope | Проверьте scopes `read_api`, `write_repository` |
| Брутфорс на веб-интерфейс | Нет rate limiting | Настройте `limit_req_zone` в Nginx |
| Доступ к БД извне | PostgreSQL слушает на 0.0.0.0 | Установите `postgresql['listen_address'] = '127.0.0.1'` |
| Утечка секретов в логи | Секреты не masked | Проверьте `masked: true` и `protected: true` для переменных |
| DoS-атака | Нет ограничений ресурсов | Настройте rate limiting, nginx limits, Sidekiq concurrency |
| Компрометация Runner'а | Привилегированный режим | Отключите `privileged` в Runner config, добавьте `cap_drop=ALL` |
| `PG::ConnectionBad` | PostgreSQL не отвечает | Проверьте статус: `gitlab-ctl status postgresql` |
| `FATAL: password authentication failed` | Неверный пароль | Проверьте `postgresql['sql_user_password']` в `gitlab.rb` |
| Отказ в обслуживании при обновлении | Недостаточно ресурсов | Настройте `maintenance mode` перед обновлением |
| Audit logs недоступны | Функция отключена | Включите в Admin Area → Settings → Audit Events |

## Лучшие практики

### Сеть

* **Firewall:** используйте host-based firewall (ufw/iptables/nftables) для ограничения входящего трафика только портами 80, 443, 2222.
* **VPN/Bastion:** доступ к административным функциям только через VPN или bastion-хост.
* **Segmentation:** отдельные подсети для management, application, database, storage;禁止 межподсетевой трафик без разрешения.
* **TLS:** используйте TLS 1.2+ с сильными шифрами; отключите устаревшие протоколы; включите HSTS и OCSP stapling.
* **Rate Limiting:** настройте rate limiting на Nginx уровне для защиты от DoS и brute-force.

### Доступ

* **2FA:** включите двухфакторную аутентификацию для всех пользователей; принудительно для администраторов.
* **SSO:** используйте LDAP/SAML/OIDC для централизованного управления доступом; отключите стандартную аутентификацию по паролю.
* **Least Privilege:** минимальные права для каждого пользователя и сервиса; используйте Group Access Tokens вместо PAT где возможно.
* **Парольная политика:** минимум 12 символов, сложность, регулярная смена; используйте password strength enforcement.
* **SSH:** только ключевая аутентификация, изменённый порт, MFA для администраторов.

### Данные

* **Шифрование:** шифруйте данные at rest (диски LUKS, БД encryption, object storage SSE).
* **Секреты:** защищайте `gitlab-secrets.json` (chmod 600, owned root:root); ротируйте секреты по графику (90 дней).
* **Бэкапы:** регулярные бэкапы с offsite-хранением и шифрованием; тестируйте восстановление регулярно (DR Drill).
* **WORM:** используйте WORM-хранилище для audit logs и критичных бэкапов.
* **Vault:** используйте HashiCorp Vault для хранения внешних секретов CI/CD вместо CI/CD переменных.

### База данных

* **Isolation:** PostgreSQL и Valkey/Redis слушают только на localhost; отключите внешний доступ.
* **Auth:** включите SCRAM-SHA-256 для PostgreSQL; используйте strong passwords для Valkey/Redis.
* **Encryption:** включите encryption at rest на уровне диска; для PostgreSQL — pgcrypto для чувствительных данных.
* **Monitoring:** отслеживайте долгие запросы (`log_min_duration_statement`), активные соединения, размер БД.

### Runner'ы

* **Isolation:** `privileged=false`, `cap_drop=ALL`, `no-new-privileges:true`, `readonly_rootfs=true`.
* **Ephemeral:** используйте одноразовые Runner'ы для untrusted код (forks, external contributors).
* **Tags:** изоляция Runner'ов по tags; protected runners только для protected branches.
* **Network:** ограничьте сеть Runner'ов; отключите доступ к внутренним сервисам.

### Мониторинг и алертинг

* **Логи:** централизованный сбор логов (ELK, Loki) с immutable storage для audit logs.
* **SIEM:** интеграция с SIEM для корреляции событий безопасности; алерты на аномалии (failed login rate, unusual API activity).
* **Алерты:** настройте алерты на подозрительную активность (failed login rate > 10/5min, rate limit exceeded, Sidekiq queue > 1000, открытый порт БД).
* **Аудит:** включите Audit Events для всех критичных операций; retention ≥ 1 год для compliance (PCI DSS).
* **DORA:** отслеживайте Security Incident Recovery Time как часть MTTR.

### Обновления и патчи

* **Patch SLA:** критичные уязвимости (CVE CVSS ≥ 7) — ≤ 7 дней; высокие (CVSS 4-6.9) — ≤ 30 дней.
* **Automation:** автоматизируйте обновления через Ansible/Chef/Puppet; тестируйте в staging перед production.
* **Maintenance Window:** плановые обновления в нерабочее время; используйте maintenance mode.
* **Rollback:** готовьте rollback-планы; храните предыдущие версии GitLab для быстрого отката.

### Инциденты

* **Runbooks:** подготовьте runbooks для типичных инцидентов (компрометация, DoS, утечка данных).
* **Tabletop Exercises:** проводите тренировки incident response каждые 6 месяцев.
* **Communication:** определите escalation path; интегрируйте с PagerDuty/OpsGenie.
* **Post-Mortem:** документируйте все инциденты; внедряйте lessons learned.

## Очистка (Cleanup)

### Удаление устаревших логов

```bash
# Очистка логов старше 30 дней (с архивацией)
sudo find /var/log/gitlab/ -name "*.log.*" -mtime +30 -delete

# Архивирование audit logs перед удалением
sudo tar -czf /backup/gitlab-audit-$(date +%Y%m%d).tar.gz /var/log/gitlab/audit/
```

### Очистка старых сессий

```bash
# Принудительный logout всех пользователей (после компрометации)
sudo gitlab-rake gitlab:sessions:clear
```

### Очистка старых бэкапов

```bash
# Удаление бэкапов старше 90 дней
sudo find /var/opt/gitlab/backups/ -name "*.tar" -mtime +90 -delete
```

## Дополнительная информация

### Связанные темы

* **[Управление инстансом GitLab](./gitlab_instance_administration.md)** — бэкап, восстановление, обновление
* **[Архитектура GitLab](../Concepts/gitlab_platform_architecture.md)** — общая архитектура и компоненты
* **[CI/CD Security Hardening](./cicd_security_hardening.md)** — безопасность на уровне пайплайнов
* **[Управление базами данных GitLab](./gitlab_database_management.md)** — PostgreSQL и Valkey/Redis
* **[Внешняя аутентификация GitLab](./gitlab_external_auth.md)** — LDAP, SAML, OIDC
* **[Compliance и Audit в GitLab CI/CD](../Advanced/compliance_and_audit.md)** — compliance frameworks и audit events
* **[Мониторинг и метрики GitLab CI/CD](../Advanced/monitoring_and_metrics.md)** — Prometheus, Grafana, алертинг
* **[Secrets Management Overview](../../Security/Concepts/secrets_management_overview.md)** — общие принципы управления секретами

### Стандарты и compliance

* **CIS GitLab Benchmark** — рекомендации по закреплению GitLab
* **NIST SP 800-53** — контрольные меры безопасности
* **GDPR** — защита персональных данных
* **SOC 2** — контроль безопасности и доступности
* **PCI DSS v4.0.1** — контроль изменений, тестирование безопасности, retention логов ≥1 года

### Ссылки

* [Официальная документация: Администрирование GitLab](https://docs.gitlab.com/administration/)
* [Официальная документация: Безопасность GitLab](https://docs.gitlab.com/ee/user/security.html)
* [Официальная документация: Securing GitLab](https://docs.gitlab.com/ee/administration/high_availability/nginx.html#securing-gitlab)
* [CIS GitLab Benchmark](https://www.cisecurity.org/benchmark/gitlab)
