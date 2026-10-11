# Сетевые требования для GitLab Runner

**Актуально для:** GitLab 17.x–19.x, GitLab Runner 17.x–19.x

## Определения

* **NetworkPolicy** — Kubernetes-ресурс, определяющий правила сетевого доступа для подов.
* **Egress** — исходящий сетевой трафик из Runner'а.
* **Ingress** — входящий сетевой трафик в Runner.
* **Air-Gapped Environment** — изолированная среда без прямого доступа к интернету.
* **Proxy** — промежуточный сервер для управления внешними соединениями.
* **Docker-in-Docker (DinD)** — режим запуска Docker-демона внутри контейнера.
* **Kubernetes Executor** — исполнитель, запускающий задачи в подах Kubernetes.
* **Docker Executor** — исполнитель, запускающий задачи в контейнерах Docker.
* **Shell Executor** — исполнитель, запускающий задачи напрямую на хосте.
* **Network Segment** — изолированный сегмент сети (VLAN, VNet, subnet).
* **Check Interval** — интервал (в секундах), с которым Runner опрашивает GitLab API на наличие новых задач (`check_interval` в `config.toml`). По умолчанию: 3 секунды. При высокой задержки сети увеличивайте значение, чтобы снизить нагрузку на API.
* **MTU (Maximum Transmission Unit)** — максимальный размер сетевого пакета. Несоответствие MTU между Runner'ом, сетью и GitLab Server приводит к фрагментации или тихому падению HTTPS-соединений.

## Предварительные требования

* GitLab CE/EE 17.x–19.x (self-hosted или GitLab.com) с доступным HTTPS API
* GitLab Runner 17.x–19.x, зарегистрированный в том же инстансе GitLab
* Роль `Maintainer`/`Owner` в проекте/группе для регистрации Runner'а; `Developer` для запуска задач
* Сеть: Runner'ы должны иметь исходящий доступ к GitLab API (TCP 443), Container Registry (TCP 443), Package Registry (TCP 443), DNS (UDP/TCP 53) и NTP (UDP 123)
* TLS: GitLab Server работает по HTTPS с валидным сертификатом. Self-signed сертификаты допустимы только в development-средах
* NTP: Синхронизация времени между GitLab Server и Runner'ами — критична для проверки JWT-подписи и артефактов
* Для Kubernetes Executor: ClusterRole с правами на создание/удаление подов, secrets и configmaps в namespace Runner'а
* Для DinD: Docker Engine 20.10+ на Runner хосте; TLS-сертификаты для DinD сервиса (рекомендуется)
* Для Air-Gapped сред: Внутренний HTTP/HTTPS proxy, GitLab Dependency Proxy или mirror для внешних образов и пакетов
* Для macOS/Windows Runner'ов: соответствующие права на установку сервиса (systemd, launchd, NSSM)

## Основные концепции

### Архитектура сетевого доступа Runner'а

Runner работает по Pull-модели: инициирует исходящие соединения к GitLab Server. Входящий трафик не требуется (за исключением Shell executor через SSH). Runner должен иметь доступ к следующим категориям ресурсов:

| Категория | Протокол/Порт | Назначение |
|:---|:---|:---|
| **GitLab API** | TCP 443 | Получение задач, отправка результатов, heartbeat |
| **GitLab Container Registry** | TCP 443 | Загрузка/скачивание образов |
| **GitLab Package Registry** | TCP 443 | Загрузка пакетов (npm, PyPI, etc.) |
| **GitLab Pages** | TCP 443 | Деплой статических сайтов |
| **Vault / Secrets Manager** | TCP 443 | Получение секретов |
| **Docker Registry** | TCP 443 | Внешние регистры образов |
| **Kubernetes API** | TCP 6443 | Деплой в кластер (Kubernetes executor) |
| **SSH** | TCP 22/2222 | Git clone/push, деплой |
| **DNS** | UDP 53, TCP 53 | Разрешение имён (TCP 53 для больших ответов) |
| **NTP** | UDP 123 | Синхронизация времени |

### Сетевые требования по типу Executor

| Executor | Входящий трафик | Исходящий трафик | Дополнительно |
|:---|:---|:---|:---|
| **Docker** | Нет | GitLab API, Registry, DNS | Порт 2376 для DinD (с TLS); порт 2375 без TLS (не рекомендуется) |
| **Kubernetes** | Нет | GitLab API, Registry, K8s API | NetworkPolicy для подов; DNS в namespace `kube-system` |
| **Shell** | SSH 2222 | GitLab API, Registry, DNS | Direct host access; требует открытого порта SSH на Runner'е |
| **Docker Machine** | Нет | GitLab API, API провайдеров инфраструктуры | **Deprecated** в GitLab 17.5, удаление в GitLab 20.0 (May 2027). Используйте Fleeting + Taskscaler для автоскейлинга |
| **Instance** | Нет | GitLab API, Registry, DNS | Эфемерная ВМ на задачу; требует доступа к API гипервизора (libvirt/KVM, VMware vSphere, Proxmox) |
| **Custom / Fleeting** | Нет | GitLab API, Registry, Hypervisor API | Зависит от плагина (libvirt/KVM, VMware vSphere, Proxmox) |

### Принцип минимальных привилегий

Runner должен иметь исходящий доступ только к whitelisted адресам. Входящий трафик не требуется (за исключением Shell executor с SSH). Используйте NetworkPolicy (Kubernetes) или host-based firewall (Linux) для ограничения egress.

## Практические сценарии

### Сценарий 1: Firewall правила для Docker Executor

```bash
# Host-based firewall (UFW) на Runner хосте

# Разрешить исходящий HTTPS
sudo ufw allow out 443/tcp comment 'GitLab API, Registry, Vault'

# Разрешить DNS (UDP для стандартных запросов, TCP для больших ответов)
sudo ufw allow out 53/udp comment 'DNS resolution'
sudo ufw allow out 53/tcp comment 'DNS TCP fallback'

# Разрешить NTP
sudo ufw allow out 123/udp comment 'NTP sync'

# Разрешить SSH для Git clone
sudo ufw allow out 22/tcp comment 'Git SSH'
sudo ufw allow out 2222/tcp comment 'GitLab SSH (custom port)'

# Запретить весь остальной исходящий трафик
sudo ufw deny out to any

# Проверка правил
sudo ufw status verbose
```

**Валидация:** Убедитесь, что правила применяются без перезагрузки:

```bash
sudo ufw reload
sudo ufw status verbose
# → Все правила должны отображаться с комментариями
```

### Сценарий 2: NetworkPolicy для Kubernetes Executor

```yaml
# network-policy-runner.yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: gitlab-runner-egress
  namespace: gitlab-runners
spec:
  podSelector:
    matchLabels:
      app: gitlab-runner
  policyTypes:
    - Egress
  egress:
    # GitLab API и Container Registry (внутренний Ingress/LoadBalancer)
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: gitlab-system
      ports:
        - protocol: TCP
          port: 443

    # Vault (внутренний IP или namespace)
    - to:
        - ipBlock:
            cidr: 10.0.0.0/8
      ports:
        - protocol: TCP
          port: 443

    # Kubernetes API
    - to:
        - namespaceSelector: {}
      ports:
        - protocol: TCP
          port: 6443

    # DNS (kube-dns/CoreDNS в namespace kube-system)
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: kube-system
      ports:
        - protocol: UDP
          port: 53
        - protocol: TCP
          port: 53

    # Внешние регистры (Docker Hub, etc.) — ограничьте по IP при возможности
    - to:
        - ipBlock:
            cidr: 0.0.0.0/0
      ports:
        - protocol: TCP
          port: 443
```

**Валидация:** Проверьте, что под Runner'а может выходить в сеть:

```bash
kubectl run network-test --image=alpine:latest --rm -it --restart=Never -- \
  sh -c "wget -q --timeout=5 https://gitlab.example.com/api/v4/version -O /dev/null && echo 'OK' || echo 'FAILED'"
# → OK
```

### Сценарий 3: Настройка Proxy для Air-Gapped среды

```yaml
# .gitlab-ci.yml — использование прокси в задачах
variables:
  HTTP_PROXY: "http://proxy.internal:3128"
  HTTPS_PROXY: "http://proxy.internal:3128"
  NO_PROXY: "gitlab.example.com,registry.gitlab.example.com,kubernetes.default.svc"

before_script:
  - |
    # Настройка git для работы через proxy
    git config --global http.proxy $HTTP_PROXY
    git config --global https.proxy $HTTPS_PROXY
```

```ruby
# /etc/gitlab/gitlab.rb — настройка прокси для GitLab Server
gitlab_rails['proxy_env'] = {
  'http_proxy' => 'http://proxy.internal:3128',
  'https_proxy' => 'http://proxy.internal:3128',
  'no_proxy' => 'gitlab.example.com,registry.gitlab.example.com'
}

# Настройка прокси для Runner
runner_proxy_env = {
  'http_proxy' => 'http://proxy.internal:3128',
  'https_proxy' => 'http://proxy.internal:3128',
  'no_proxy' => 'gitlab.example.com,registry.gitlab.example.com'
}
```

**Валидация:** Проверьте, что прокси не используется для внутренних адресов:

```bash
curl -I --noproxy "*" https://gitlab.example.com/api/v4/version
# → HTTP/2 200 (должен идти напрямую, без прокси)
```

### Сценарий 4: Docker-in-Docker сеть

```yaml
# .gitlab-ci.yml — DinD с TLS
services:
  - name: docker:24.0-dind
    alias: docker
    command: ["--tlsverify", "--tlscacert=/certs/ca.pem", "--tlscert=/certs/server.pem", "--tlskey=/certs/server-key.pem", "-H", "tcp://0.0.0.0:2376"]

variables:
  DOCKER_HOST: tcp://docker:2376
  DOCKER_TLS_CERTDIR: "/certs"
  DOCKER_DRIVER: overlay2

# Проверка connectivity
test:
  image: docker:24.0
  script:
    - docker info
    - docker run --rm alpine:latest echo "DinD works"
```

```bash
# Firewall правила для DinD
# Runner должен иметь доступ к порту 2376 на сервисе docker:dind
# В Kubernetes: NetworkPolicy должна разрешать egress к сервису docker на порт 2376

# Проверка порта
nc -zv docker 2376
# → Connection to docker 2376 port [tcp/tls] succeeded!
```

**Валидация:** Убедитесь, что TLS включён:

```bash
docker --tlsverify --tlscacert=/certs/ca.pem --tlscert=/certs/client.pem --tlskey=/certs/client-key.pem -H tcp://docker:2376 info
# → Должен вернуть информацию о Docker daemon без ошибок сертификатов
```

### Сценарий 5: Проверка сетевой connectivity из Runner'а

```bash
# Диагностический job для проверки сети
network_test:
  image: alpine:latest
  script:
    # DNS resolution
    - nslookup gitlab.example.com
    - dig registry.gitlab.example.com

    # Connectivity tests
    - wget -q --timeout=5 https://gitlab.example.com/api/v4/version -O /dev/null
    - wget -q --timeout=5 https://registry.gitlab.example.com/v2/ -O /dev/null

    # Port checks
    - nc -zv -w5 gitlab.example.com 443
    - nc -zv -w5 registry.gitlab.example.com 443

    # Traceroute для диагностики задержек
    - traceroute -T -p 443 gitlab.example.com
```

**Валидация:** Все команды должны завершаться с кодом 0. При использовании минимальных образов (alpine, scratch) может потребоваться установка `traceroute` и `bind-tools` отдельно:

```bash
apk add --no-cache traceroute bind-tools nmap-ncat
```

## Дополнительная информация

### См. также

* **[Управление парком Runner'ов](../../Advanced/runner_fleet_management.md)** — масштабирование и конфигурация
* **[Kubernetes Executor](../../Advanced/gitlab_ci_runners_executors.md)** — настройка K8s executor
* **[GitLab Runner в Kubernetes](../../../Kubernetes/Installation/gitlab_runner_kubernetes_installation.md)** — установка Runner в K8s
* **[CI/CD Security Hardening](../../Advanced/cicd_security_hardening.md)** — изоляция и безопасность
* **[Proxy и Air-Gapped GitLab CI](../../Tutorials/proxy_air_gapped_gitlab_ci.md)** — работа в закрытом контуре

### Чек-лист сетевой изоляции

- [ ] Runner имеет доступ только к whitelisted адресам
- [ ] DNS разрешение работает корректно (UDP и TCP 53)
- [ ] NTP синхронизация настроена
- [ ] Firewall/NetworkPolicy настроены для egress
- [ ] В случае DinD: порт 2376 открыт только для Runner и используется TLS
- [ ] Proxy настроен для air-gapped сред; `NO_PROXY` исключает внутренние адреса
- [ ] MTU настроен единообразно на всех сетевых интерфейсах
- [ ] TLS-сертификаты валидны (не self-signed в production)
- [ ] `check_interval` настроен с учётом задержки сети между Runner'ом и GitLab Server
- [ ] Мониторинг сетевых метрик (latency, packet loss) настроен

## Устранение неполадок

| Проблема | Причина | Диагностика | Решение |
|:---|:---|:---|:---|
| **Runner не берёт задачи в работу** | Сеть недоступна, `concurrent=0`, неверный токен | `gitlab-runner verify`; `curl -I $CI_SERVER_URL`; `journalctl -u gitlab-runner` | Проверьте firewall, DNS, registration token; убедитесь что `concurrent > 0` |
| **Задача висит в `pending`** | Нет matching runner'ов с нужными тегами, `concurrent` исчерпан | `gitlab-runner list`; метрики Queue Time | Проверьте `tags` в `.gitlab-ci.yml` и `concurrent`/`limit` в `config.toml` |
| **Таймаут при клонировании репозитория** | Высокая задержка сети, MTU mismatch, DNS не разрешает | `git clone --verbose`; `ping -M do $CI_SERVER_HOST`; `traceroute` | Увеличьте `git_lfs_support` или `clone_timeout`; проверьте MTU на интерфейсах |
| **Не удаётся скачать образ** | Registry недоступен, proxy блокирует, сертификат невалиден | `curl -I https://registry.gitlab.example.com/v2/`; `docker pull` с verbose | Проверьте доступность registry, настройки proxy, валидность TLS-сертификата |
| **DNS не разрешает имена** | DNS сервер недоступен, локальный кэш устарел | `nslookup`, `dig`, `cat /etc/resolv.conf` | Проверьте `/etc/resolv.conf`, доступность DNS серверов (UDP/TCP 53) |
| **MTU mismatch / фрагментация** | Разный MTU на сетевом пути (например, 1500 vs 1400) | `ping -M do -s 1472 $CI_SERVER_HOST`; `tcpdump` | Установите единый MTU (обычно 1400 для VPN/оверлеев, 1500 для LAN) на Runner'е и промежуточных устройствах |
| **TLS-сертификат не доверен** | Self-signed cert, expired cert, неверный CN/SAN | `openssl s_client -connect gitlab.example.com:443`; `curl -v` | Установите CA-сертификат в trust store Runner'а; используйте валидный cert в production |
| **DinD: соединение с docker:dind падает** | TLS не настроен, порт 2375 открыт без ограничений, NetworkPolicy блокирует | `nc -zv docker 2376`; логи Runner'а | Используйте TLS (`DOCKER_TLS_CERTDIR`), ограничьте порт 2376 только Runner'ом |
| **Задачи отменяются при `auto_cancel`** | Высокая задержка сети приводит к race condition | Логи пайплайна, метрики `gitlab_runner_job_canceled_total` | Увеличьте `check_interval`; проверьте стабильность сети между Runner'ом и GitLab |

## Рекомендации

* **Ограничивайте egress по умолчанию.** Настройте firewall или NetworkPolicy до добавления Runner'ов в эксплуатацию. Разрешайте только необходимые порты и IP-диапазоны.
* **Используйте TLS везде.** Отключайте TLS только в development-средах. В production используйте валидные сертификаты от публичного или внутреннего CA.
* **Мониторьте задержку сети.** Высокий RTT между Runner'ом и GitLab Server увеличивает время получения задач. Размещайте Runner'ы в том же дата-центре, что и GitLab Server.
* **Настраивайте `check_interval` с запасом.** При задержке сети > 200 ms увеличивайте `check_interval` до 5–10 секунд, чтобы снизить частоту heartbeat-запросов.
* **Используйте ephemeral Runner'ы.** Не-permanent Runner'ы снижают риск утечки данных и упрощают обновление образа/конфигурации.
* **Ведите inventory сетевых правил.** Документируйте firewall/NetworkPolicy правила для каждого Runner'а. При изменении инфраструктуры проверяйте актуальность правил.
* **Проверяйте MTU после изменений сети.** При добавлении VPN, VLAN или оверлейных сетей (VXLAN, Geneve) проверяйте MTU на всех участках пути.
* **Не открывайте порт 2375 для DinD без TLS.** Порт 2375 без аутентификации даёт полный доступ к Docker daemon и является критической уязвимостью.
* **Используйте `NO_PROXY` для внутренних адресов.** Указывайте в `NO_PROXY` все внутренние сервисы (GitLab, Registry, Vault, K8s API), чтобы трафик не шёл через внешний proxy.
