# Развертывание в традиционной инфраструктуре (Bare Metal / VM)

## Определения

- **Традиционная инфраструктура** — серверные ресурсы, представленные физическим оборудованием (Bare Metal) или виртуальными машинами (VM), управление которыми осуществляется напрямую через ОС, а не через высокоуровневые API оркестраторов типа Kubernetes.
- **Мутабельная инфраструктура (Mutable Infrastructure)** — подход, при котором изменения вносятся непосредственно в работающие серверы (например, через SSH или конфигурационное управление). Серверы живут долго и «накапливают» состояние.
- **Иммутабельная инфраструктура (Immutable Infrastructure)** — подход, при котором серверы не обновляются «на месте». Для внесения изменений создается новый образ (Golden Image), развертываются новые серверы, а старые уничтожаются.
- **Golden Image (Золотой образ)** — предварительно настроенный и протестированный образ диска или виртуальной машины, содержащий ОС, системные зависимости, агенты мониторинга и само приложение, готовый к немедленному запуску.
- **Конфигурационное управление (CM)** — инструменты автоматизации настройки серверов (Ansible, Chef, Puppet, SaltStack), обеспечивающие декларативное описание целевого состояния.
- **Внутренняя платформа разработчика (Internal Developer Platform, IDP)** — набор инструментов и сервисов, предоставляющий разработчикам «Золотые пути» (Golden Paths) для самообслуживания инфраструктурой, включая автоматизированный заказ VM и Bare Metal.
- **SBOM (Software Bill of Materials)** — структурированный перечень всех компонентов, библиотек и зависимостей, включенных в образ или артефакт, необходимый для обеспечения безопасности цепочки поставок (Supply Chain Security).
- **Micro-VM** — легковесные виртуальные машины (например, Firecracker), обеспечивающие изоляцию аппаратного уровня с быстротой запуска контейнеров.
- **Идемпотентность (Idempotency)** — свойство операции давать один и тот же итоговый результат при многократном применении. Фундамент CM (Ansible/Puppet/Salt): повторный прогон плейбука приводит сервер в целевое состояние, не ломая уже корректные участки.
- **Zero-Downtime Deployment (Развертывание без простоя)** — доставка новой версии так, что пользователи не замечают перерыва в обслуживании: достигается переключением трафика, поэтапной заменой узлов или корректным (graceful) завершением старых процессов.
- **Репозиторий артефактов (Artifact Repository)** — внутреннее хранилище неизменяемых релизов (Nexus, Artifactory, Harbor), единый источник достоверных бинарников с контролем подлинности по подписи и хэшу.
- **ZTP (Zero-Touch Provisioning)** — бесконтактная инициализация «голого» железа или VM: от сетевой загрузки (PXE/iPXE) до регистрации в оркестраторе/CM без ручного участия.

---

## Основные концепции

### Эволюция подходов: От ручной автоматизации к Platform Engineering

В современной практике развертывание в традиционной среде перестало быть «ручным» процессом и интегрировалось в общую экосистему Platform Engineering. Основной фокус сместился на автономность, безопасность и экономическую эффективность (FinOps).

#### Паттерны деплоя в традиционной среде

| Паттерн | Описание | Инструменты | Подход |
| :--- | :--- | :--- | :--- |
| **Agentless Push (SSH)** | CI-раннер инициирует соединение и выполняет плейбуки. Требует JIT-доступа (Just-in-Time). | Ansible, Fabric, SSH. | Мутабельный |
| **Agent-based Pull (GitOps)** | Агент на хосте периодически синхронизирует состояние с Git-репозиторием. | Ansible-pull, Salt-minion. | Мутабельный |
| **Image-based Deployment** | Полная замена инстансов на основе обновленных Golden Images. Минимизирует дрифт. | Packer, Terraform, Cloud-init. | Иммутабельный |
| **Hybrid Orchestration** | Запуск гетерогенных нагрузок (бинарники + контейнеры) через единый Control Plane. | HashiCorp Nomad, Proxmox. | Гибридный |
| **Bare Metal Provisioning (PXE/ZTP)** | Управление физическими серверами как автономными узлами через сеть (без облачных API). | MAAS, Ironic, Tinkerbell. | Иммутабельный |

#### Оркестрация против конфигурационного управления

Важно различать два уровня автоматизации, которые часто путают:

- **Configuration Management (Ansible/Puppet/Chef)** управляет *состоянием* уже существующих узлов: «что установлено, какие конфиги, какие сервисы запущены». Хорошо для долгоживущих мутабельных серверов.
- **Orchestration / Scheduler (Nomad, Proxmox)** управляет *жизненным циклом задач* на пуле узлов: «где запустить, перезапустить при падении, масштабировать». Ближе к иммутабельному подходу.

В традиционной среде они часто комбинируются: Nomad планирует задачи, а Ansible готовит базовый слой узлов (hardening, агенты). Подробности гетерогенной оркестрации — в **[Nomad: практические сценарии](../../Nomad/practical_scenarios.md)**.

### Жизненный цикл деплоя (актуальный)

1.  **Zero-Touch Provisioning (ZTP):** Автоматическое обнаружение и базовая настройка нового «железа» или VM при включении.
2.  **Secure-by-Design Boot:** Проверка целостности прошивки и загрузчика (Secure Boot, TPM 2.0).
3.  **Policy-as-Code Validation:** Проверка конфигурации на соответствие стандартам безопасности (OPA, `ansible-lint`) до начала деплоя.
4.  **Artifact Deployment & SBOM Signing:** Доставка артефактов с проверкой криптографических подписей.
5.  **Runtime Attestation:** Постоянный мониторинг целостности системы и обнаружение дрифта в реальном времени.
6.  **Observability-driven Verification:** Smoke-тесты на основе метрик (eBPF/Node Exporter) для проверки сетевой связности и производительности I/O.
7.  **FinOps & Green Tracking:** Сбор данных об энергопотреблении и стоимости эксплуатации ресурсов после деплоя.

### Стратегии развертывания в традиционной инфраструктуре

Стратегии (Rolling, Blue-Green, Canary, Shadow) — это над-технологичные паттерны; в традиционной среде они реализуются иначе, чем в Kubernetes, потому что нет объекта `Service` для мгновенного переключения селектора. Переключение трафика ложится на балансировщик (HAProxy/Nginx), плавающий IP (VRRP/keepalived) или атомарную смену симлинка. Ниже — карта соответствия; детальные конфигурации вынесены в профильные материалы (не дублируются здесь):

| Стратегия | Механизм переключения на Bare Metal / VM | Авторитетный материал |
| :--- | :--- | :--- |
| **Rolling** | Ansible `serial` + поэтапный вывод/ввод узлов в балансировщик; ступенчатое изменение веса. | **[Rolling Update](./rolling_update.md)** |
| **Blue-Green** | VRRP/keepalived (Floating VIP), `enable/disable` в HAProxy, flip symlink. | **[Сине-зеленое развертывание](./blue_green_deployment.md)**, **[Keepalived (VRRP)](../../Networking/ServicesAndTools/keepalived_overview.md)** |
| **Canary** | Часть трафика на пул Green через вес в HAProxy/Nginx (Traefik). | **[Канареечное развертывание](./canary_deployment.md)** |
| **Shadow** | Зеркалирование (mirror) через Nginx/Envoy без ответа клиенту. | **[Shadow Deployment](./shadow_deployment.md)** |

Инфраструктурный фундамент, делающий эти стратегии возможными на «голом» железе, описан в практических сценариях ниже: провизия (ZTP/PXE), мгновенный откат (LVM), корректный перезапуск (systemd), целостность артефакта (подпись). Общая матрица выбора — в **[сравнении стратегий](./comparison.md)**.

---

## Практические сценарии

### Сценарий 1: Продвинутый CI/CD через Ansible (Push-модель)

Используется для систем, где полная замена VM невозможна или нецелесообразна (например, тяжелые БД).

**Предварительные требования:**
- Ansible 2.15+ на раннере.
- Доступ по SSH через JIT-шлюз (например, Teleport или HashiCorp Boundary).
- Хранилище секретов HashiCorp Vault.

**Рабочий процесс (GitLab CI):**
```yaml
deploy_app:
  stage: deploy
  script:
    - export VAULT_TOKEN=$(vault read -field=token auth/approle/login role_id="$VAULT_ROLE_ID" secret_id="$VAULT_SECRET_ID")
    - ansible-lint playbooks/deploy.yml
    - ansible-playbook -i inventory/prod.ini playbooks/deploy.yml \
        --extra-vars "app_version=${CI_COMMIT_TAG}"
```

**Плейбук (playbooks/deploy.yml):**
```yaml
- hosts: app_servers
  become: true
  vars:
    app_path: "/opt/apps/my-service"
    db_password: "{{ lookup('community.hashi_vault.vault_kv2_get', 'prod/db').secret.password }}"

  tasks:
    - name: "Verification: Check free space"
      assert:
        that: "ansible_mounts[0].size_available > 500000000"
        fail_msg: "Insufficient disk space for deployment"

    - name: "Download and Verify Artifact"
      get_url:
        url: "https://artifactory.local/my-app-{{ app_version }}.tar.gz"
        dest: "/tmp/my-app.tar.gz"
        checksum: "sha256:{{ lookup('url', 'https://artifactory.local/my-app.sha256') }}"

    - name: "Extract to versioned directory"
      unarchive:
        src: "/tmp/my-app.tar.gz"
        dest: "{{ app_path }}-{{ app_version }}"
        remote_src: yes

    - name: "Update Symbolic Link (Atomic switch)"
      file:
        src: "{{ app_path }}-{{ app_version }}"
        dest: "{{ app_path }}/current"
        state: link
      notify: "Restart and Validate Service"

  handlers:
    - name: "Restart and Validate Service"
      systemd:
        name: my-service
        state: restarted
        enabled: true
      register: service_status
      failed_when: service_status.state != 'started'

  post_tasks:
    - name: "Health check after deploy"
      uri:
        url: "http://{{ inventory_hostname }}:8080/healthz"
        status_code: 200
      register: hc
      retries: 5
      delay: 3
      until: hc.status == 200
      ignore_errors: true
    - name: "Atomic rollback of symlink on health failure"
      file:
        src: "{{ app_path }}/previous"
        dest: "{{ app_path }}/current"
        state: link
      notify: "Restart and Validate Service"
      when: hc.status != 200
```

> Близкий пример доставки (Ansible Push + systemd + Canary) — в **[паттернах CI/CD](../ci_cd_patterns.md)**.

### Сценарий 2: Immutable Infrastructure (Packer + Terraform + Cloud-init)

Золотой стандарт для масштабируемых веб-приложений и stateless-сервисов.

**Этапы:**
1.  **Bake (Сборка):** Packer создает образ, устанавливая зависимости и генерируя SBOM.
    ```hcl
    # packer/template.pkr.hcl
    build {
      sources = ["source.vsphere.ubuntu"]
      provisioner "ansible" {
        playbook_file = "./setup.yml"
      }
      post-processor "manifest" {
        output = "manifest.json"
      }
    }
    ```
2.  **Verify:** Сканирование образа на уязвимости (Trivy/Clair).
3.  **Deploy (Развертывание):** Terraform обновляет шаблон в Auto Scaling Group или гипервизоре.
    ```hcl
    resource "vsphere_virtual_machine" "app" {
      name             = "app-${var.app_version}"
      clone {
        template_uuid = data.vsphere_virtual_machine.template.id
      }
      extra_config = {
        "guestinfo.userdata" = base64encode(data.template_file.cloud_init.rendered)
      }
    }
    ```

**Validation:** Cloud-init выполняет финальную настройку (регистрация в Consul/DNS) и сигнализирует о готовности через эндпоинт мониторинга.

### Сценарий 3: GitOps для VM через Ansible-pull

Подход, исключающий необходимость открытого SSH-порта на серверах.

**Механизм:**
- На каждом сервере настроен `cron` или `systemd-timer`, запускающий `ansible-pull`.
- Агент скачивает изменения из Git и применяет их локально.

```bash
# Пример команды запуска
ansible-pull -U https://git.company.com/infra/config.git \
             -i localhost, \
             local.yml
```

### Сценарий 4: Rolling Update через Ansible (serial + health probe)

Поэтапная замена версии на пуле узлов без простоя. Ключевые принципы: обновляем батчами (`serial`), выводим узел из балансировщика перед рестартом, проверяем готовность, возвращаем в пул.

```yaml
# rolling_update.yml — поэтапная замена без простоя
- hosts: app_servers
  become: true
  serial: 2                  # обновляем по 2 узла за раз (размер батча)
  max_fail_percentage: 20    # остановить прогон, если упало >20% узлов
  vars:
    app_version: "{{ app_version }}"
  tasks:
    - name: "Drain: вывести узел из пула (HAProxy)"
      command: >-
        socat stdio /var/run/haproxy.sock <<< "disable server app/{{ inventory_hostname }}"
      delegate_to: "{{ groups['lb'][0] }}"
      ignore_errors: true

    - name: "Доставить и распаковать релиз (atomic symlink)"
      unarchive:
        src: "/tmp/my-app-{{ app_version }}.tar.gz"
        dest: "/opt/apps/my-service-{{ app_version }}"
        remote_src: yes

    - name: "Переключить symlink и перезапустить (graceful)"
      file: { src: "/opt/apps/my-service-{{ app_version }}", dest: "/opt/apps/my-service/current", state: link }
      notify: "Restart and Validate Service"

    - name: "Дождаться готовности (health probe)"
      wait_for:
        host: "{{ inventory_hostname }}"
        port: 8080
        timeout: 30

    - name: "Вернуть узел в пул"
      command: >-
        socat stdio /var/run/haproxy.sock <<< "enable server app/{{ inventory_hostname }}"
      delegate_to: "{{ groups['lb'][0] }}"
```

> Глубокий разбор Rolling на Bare Metal и дополнительные приёмы (throttle, `max_fail_percentage`) — в **[Rolling Update](./rolling_update.md)** и **[Ansible: стратегии деплоя](../../Ansible/ansible_deployment_strategies.md)**.

### Сценарий 5: Bare Metal Provisioning через PXE/iPXE + ZTP (MAAS/Ironic)

Автономная провизия физических серверов без ручной установки ОС. Поток: DHCP (Option 60/66/67) → TFTP-загрузчик → ядро/initrd → автоинсталляция (preseed/kickstart/cloud-init) → first-boot регистрация через ansible-pull.

**Минимальный PXE-сервер на dnsmasq (ProxyDHCP + TFTP):**
```bash
cat > /etc/dnsmasq.d/pxe.conf <<'EOF'
interface=eth0
dhcp-range=192.168.10.50,192.168.10.150,12h
dhcp-boot=pxelinux.0
enable-tftp
tftp-root=/srv/tftp
EOF
systemctl restart dnsmasq
```

**cloud-init (user-data) для first-boot настройки:**
```yaml
# /srv/tftp/seed/user-data
runcmd:
  - ansible-pull -U https://git.company.com/infra/config.git local.yml
  - systemctl enable --now node-exporter
```

**Валидация:**
```bash
ipmitool -H bmc-1 -U admin chassis status        # BMC доступен
journalctl -u cloud-final -n 20                  # first-boot завершён
# → узел появился в инвентаре CM и отвечает на :9100 (Node Exporter)
```

> Протокол загрузки и опции DHCP — в **[PXE: сетевая загрузка](../../Linux/Networking/Concepts/pxe_boot.md)**.

### Сценарий 6: Мгновенный откат через LVM-снимок

Перед рискованным деплоем снимаем снимок логического тома; при сбое — слияние снимка возвращает состояние ФС за секунды (быстрее полной переустановки).

```bash
# Перед деплоем — снимок тома с приложением
lvcreate -L 2G -s -n app_snap /dev/vg0/app

# ... выполняем деплой (Сценарии 1/4) ...

# Откат при сбое:
umount /opt/app/current
lvconvert --merge /dev/vg0/app_snap     # возврат ФС к моменту снимка
mount /opt/app/current
systemctl restart my-service
```

**Валидация:** `lvs` показывает `app_snap` до merge; после merge снимок исчезает, `mountpoint /opt/app/current` — `mounted`.

> Механика снимков и тонкости производительности — в **[LVM — снимки](../../Linux/FileSystems/LVM/snapshots.md)**.

### Сценарий 7: Zero-Downtime через systemd (graceful shutdown, reload, socket activation)

Корректный перезапуск процесса критичен: при SIGTERM приложение должно перестать принимать новые соединения и дождаться текущих. Юнит настраивается явно.

```ini
# /etc/systemd/system/my-service.service
[Unit]
Description=My Service
After=network.target

[Service]
Type=notify
ExecStart=/opt/app/current/bin/server
ExecReload=/bin/kill -HUP $MAINPID
KillSignal=SIGTERM
TimeoutStopSec=30
Restart=on-failure
AmbientCapabilities=CAP_NET_BIND_SERVICE

[Install]
WantedBy=multi-user.target
```

Ключевые приёмы:
- `systemctl reload my-service` — для смены конфигурации без разрыва (приложение должно ловить HUP).
- `systemctl reload-or-restart my-service` — безопасная попытка reload, иначе restart.
- **Socket activation:** вынос слушающего сокета в отдельный `my-service.socket` позволяет перезапускать сам сервис, не теряя входящие соединения в момент рестарта (сокет держит systemd).

**Валидация:**
```bash
systemctl is-active my-service     # → active
systemctl reload my-service && systemctl is-active my-service
```

> Graceful-shutdown со стороны балансировщика — в **[балансировке нагрузки HTTP](../../Networking/Protocols/HTTP/http_load_balancing.md)**.

### Сценарий 8: Подпись и верификация артефактов (Supply Chain Security)

Перед раскаткой на узлы артефакт должен быть подписан, а на хосте — проверен. Это предотвращает установку подменённого бинарника.

```bash
# Подпись образа/артефакта в pipeline (cosign)
cosign sign --key cosign.key nexus.internal:5000/my-app:1.4.0

# Верификация на хосте ДО деплоя
cosign verify --key cosign.pub nexus.internal:5000/my-app:1.4.0 \
  && echo "OK: подпись валидна"

# Альтернатива для tar.gz — GPG
gpg --verify my-app.tar.gz.sig my-app.tar.gz
```

**Валидация:** при невалидной подписи `cosign verify` завершается с ненулевым кодом → шаг деплоя прерывается.

> Генерация SBOM и уязвимостный гейт (syft + grype) — в **[управлении артефактами](../../CI-CD/artifact_management.md)**.

### Сценарий 9: Post-deploy верификация (synthetic / infra tests)

После переключения трафика обязателен автоматический прогон проверок — это Health Gate перед закрытием окна.

```bash
# Быстрая проверка endpoints
curl -fsS http://localhost:8080/healthz && echo "health OK"

# Инфраструктурный тест (goss) — декларативная проверка состояния хоста
goss validate --format tap
```

Типовой набор проверок: доступность `/healthz`, корректность версии в `/version`, наличие слушающего порта, отсутствие ошибок в `journalctl -u my-service` за последние N минут. При падении проверок — автоматический откат (см. Сценарий 1 post_tasks, Сценарий 6). Механизмы автоматического отката — в **[Health Checks и Rollback](./deployment_health_checks_and_rollback.md)**.

---

## Операции и команды

Ниже — быстрые справочники по основным инструментам традиционного деплоя. Полные конфигурации — в практических сценариях и профильных документах.

### Ansible

| Команда | Назначение | Пример |
| :--- | :--- | :--- |
| `ansible-lint` | Статическая проверка плейбуков | `ansible-lint playbooks/deploy.yml` |
| `ansible-playbook` | Запуск деплоя | `ansible-playbook -i inventory/prod.ini playbooks/deploy.yml --extra-vars "app_version=1.2.3"` |
| `ansible-playbook --check --diff` | Детекция дрифта без применения | `ansible-playbook -i inventory/prod.ini playbooks/hardening.yml --check --diff` |
| `ansible-pull` | Pull-модель (без открытого SSH) | `ansible-pull -U https://git.company.com/infra/config.git local.yml` |

### Packer

| Команда | Назначение | Пример |
| :--- | :--- | :--- |
| `packer build` | Сборка Golden Image | `packer build -var 'app_version=1.4.0' ./packer/template.pkr.hcl` |
| `packer inspect` | Просмотр шаблона | `packer inspect ./packer/template.pkr.hcl` |

### Terraform

| Команда | Назначение | Пример |
| :--- | :--- | :--- |
| `terraform plan` | Превью изменений инфраструктуры | `terraform plan -var='app_version=1.4.0'` |
| `terraform apply` | Применение изменений | `terraform apply -auto-approve` |
| `terraform state list` | Просмотр текущего состояния | `terraform state list` |

### keepalived / VRRP

| Команда / Проверка | Назначение | Пример |
| :--- | :--- | :--- |
| `systemctl status keepalived` | Проверка работы VRRP | `systemctl status keepalived` |
| `ip addr show` | Проверка VIP на интерфейсе | `ip addr show eth0` |
| `tcpdump` | Диагностика VRRP-пакетов | `tcpdump -i eth0 proto 112` |

### HAProxy

| Команда | Назначение | Пример |
| :--- | :--- | :--- |
| `socat` runtime API | Вывод/возврат узла из пула | `echo "disable server app/web01" | socat stdio /var/run/haproxy.sock` |
| `echo show stat` | Сбор метрик пула | `echo "show stat" | socat stdio /var/run/haproxy.sock \| cut -d ',' -f 1,2,18,24` |
| `haproxy -c` | Проверка конфигурации | `haproxy -c -f /etc/haproxy/haproxy.cfg` |

### Nginx

| Команда | Назначение | Пример |
| :--- | :--- | :--- |
| `nginx -t` | Проверка конфигурации | `nginx -t` |
| `nginx -s reload` | Горячая перезагрузка конфигурации | `nginx -s reload` |
| `curl` upstream | Проверка маршрутизации upstream | `curl -H "Host: app.example.com" http://lb/` |

### systemd

| Команда | Назначение | Пример |
| :--- | :--- | :--- |
| `systemctl restart` | Рестарт юнита | `systemctl restart my-service` |
| `systemctl reload` | Перезагрузка конфигурации без разрыва | `systemctl reload my-service` |
| `systemctl reload-or-restart` | Безопасная попытка reload, иначе restart | `systemctl reload-or-restart my-service` |
| `systemctl set-property` | Изменение лимитов cgroup на живом процессе | `systemctl set-property myapp.service MemoryMax=2G CPUQuota=150%` |
| `systemctl is-active` | Проверка состояния | `systemctl is-active my-service` |
| `journalctl -u` | Просмотр логов сервиса | `journalctl -u my-service -n 50` |

### LVM

| Команда | Назначение | Пример |
| :--- | :--- | :--- |
| `lvcreate -s` | Создание снимка для отката | `lvcreate -L 2G -s -n app_snap /dev/vg0/app` |
| `lvconvert --merge` | Слияние снимка (откат ФС) | `lvconvert --merge /dev/vg0/app_snap` |
| `lvs` | Проверка состояния томов | `lvs` |

### dnsmasq / PXE

| Команда | Назначение | Пример |
| :--- | :--- | :--- |
| `systemctl restart dnsmasq` | Применение конфигурации PXE | `systemctl restart dnsmasq` |
| `cat /etc/dnsmasq.d/pxe.conf` | Проверка опций DHCP/TFTP | `cat /etc/dnsmasq.d/pxe.conf` |

### Подпись артефактов

| Команда | Назначение | Пример |
| :--- | :--- | :--- |
| `cosign sign` | Подпись образа | `cosign sign --key cosign.key nexus.internal:5000/my-app:1.4.0` |
| `cosign verify` | Верификация подписи образа | `cosign verify --key cosign.pub nexus.internal:5000/my-app:1.4.0` |
| `gpg --verify` | Верификация tar.gz/файла | `gpg --verify my-app.tar.gz.sig my-app.tar.gz` |
| `syft` | Генерация SBOM | `syft nexus.internal:5000/my-app:1.4.0 -o spdx-json` |
| `grype` | Сканирование уязвимостей | `grype nexus.internal:5000/my-app:1.4.0` |

### Валидация и Observability

| Команда | Назначение | Пример |
| :--- | :--- | :--- |
| `curl -fsS` | Быстрый health-check эндпоинта | `curl -fsS http://localhost:8080/healthz` |
| `goss validate` | Декларативная проверка состояния хоста | `goss validate --format tap` |
| `journalctl -u` | Логи сервиса за последние N строк | `journalctl -u my-service -n 50` |
| `systemctl is-active` | Проверка, что сервис запущен | `systemctl is-active my-service` |
| `chronyc tracking` | Статус синхронизации времени | `chronyc tracking` |
| `ipmitool chassis status` | Проверка BMC железа | `ipmitool -H bmc-1 -U admin chassis status` |
| `nvme smart-log` | Состояние NVMe-накопителя | `nvme smart-log /dev/nvme0` |
| `iostat -xz 1` | Утилизация дисков в реальном времени | `iostat -xz 1` |
| `mtr` | Трассировка маршрута с диагностикой потерь | `mtr google.com` |
| `ethtool -S` | Статистика ошибок на NIC | `ethtool -S eth0` |

---

## Устранение неполадок (Troubleshooting)

### Обнаружение дрифта (Drift Detection)
- **Сценарий:** Конфигурация на сервере отличается от описанной в Git.
- **Решение:** Запуск Ansible в режиме проверки (`--check --diff`). Использование **Terraform Drift Detection** в CI/CD для выявления изменений, внесенных вручную через консоль гипервизора.

### Проблемы с производительностью I/O
- **Симптомы:** Высокий `iowait`, задержки в работе БД.
- **Диагностика:**
  - `iostat -xz 1` — анализ утилизации дисков.
  - `nvme smart-log /dev/nvme0` — проверка состояния NVMe-накопителей.
- **Тюнинг:** Настройка планировщика I/O (`deadline` или `none` для SSD) и параметров `dirty_ratio` в `sysctl`.

### Сетевые задержки и потери пакетов
- **Диагностика:**
  - `mtr` — поиск узких мест в маршруте.
  - `ethtool -S eth0` — поиск ошибок на физическом уровне (CRC errors, drops).
- **Решение:** Проверка соответствия MTU на всех участках сети, тюнинг очередей сетевой карты (`ethtool -G`).

### Рассинхронизация времени (Clock Drift)
- **Сценарий:** Ошибки в работе распределенных систем (Kafka, Cassandra).
- **Решение:** Переход на `chrony` с указанием нескольких PTP или stratum-1 источников. Проверка статуса через `chronyc tracking`.

### Частичный деплой (partial state)
- **Сценарий:** Плейбук упал на середине пула — часть узлов обновлена, часть — нет.
- **Решение:** Благодаря идемпотентности Ansible повторный прогон корректно доведёт оставшиеся узлы (`--limit` на нужную группу). Зафиксируйте, какие узлы уже в новой версии, и докатайте только их.

### Битый symlink после switch
- **Сценарий:** `current` указывает на несуществующий каталог версии → сервис не стартует.
- **Решение:** Перед рестартом проверять `stat {{ app_path }}/current`; при сбое — атомарно вернуть ссылку на предыдущую версию (`ln -sfn <prev> current`) и перезапустить.

### Сервис не стартует после рестарта
- **Диагностика:** `journalctl -u my-service -n 50`, `systemctl status my-service`.
- **Решение:** Вернуть symlink на предыдущую версию (atomic rollback) и перезапустить; разбирать причину (права, порт занят, нехватка памяти) отдельно вне окна.

### Нет JIT/SSH доступа
- **Сценарий:** Teleport/Boundary недоступны, Push-деплой невозможен.
- **Решение:** Использовать pull-модель (Сценарий 3) — агент сам заберёт изменения из Git при следующем тике `ansible-pull`.

### Ошибка аттестации (Keylime/Spire)
- **Сценарий:** Узел не получает динамический сертификат, отказано в доступе к сервисам.
- **Решение:** Проверить Measurements/TPM (`keylime_verifier` логи), при необходимости перевести узел в карантин и переаттестовать.

### Нехватка места при распаковке
- **Симптомы:** `No space left on device` на шаге `unarchive`.
- **Решение:** Очистить старые релизы (`rm -rf /opt/apps/my-service-vOLD`), поднять threshold `assert` (Сценарий 1), освободить место под `/tmp`.

### VIP не мигрирует (keepalived)
- **Сценарий:** Blue-Green switch через VRRP не происходит, VIP остается на старой среде.
- **Решение:** Проверить доступность multicast/unicast между узлами (`tcpdump -i eth0 proto 112`), убедиться что `priority` различается, firewall не блокирует VRRP.

### HAProxy сокет недоступен
- **Сценарий:** `socat stdio /var/run/haproxy.sock` возвращает `Connection refused`.
- **Решение:** Проверить `ls -l /var/run/haproxy.sock` и права; убедиться что `stats socket` объявлен в `haproxy.cfg`; перезапустить HAProxy.

### DNS TTL ломает Zero-Downtime
- **Сценарий:** После switch часть клиентов все еще стучится на старый IP из-за кэширования.
- **Решение:** Использовать L7-веса/VRRP вместо DNS-based переключения; DNS понижать TTL только как крайняя мера.

### Graceful Shutdown не успевает завершить запросы
- **Сценарий:** Приложение получает `SIGTERM`, но долгие запросы обрываются.
- **Решение:** Увеличить `TimeoutStopSec` в systemd-юните до покрытия P99 длительности + запас; добавить явный обработчик сигнала в код; увеличить лимит активных соединений перед `SIGTERM`.

### Connection Draining зависает
- **Сценарий:** HAProxy/Nginx не ждет завершения long-polling/WebSocket при drain.
- **Решение:** Увеличить `timeout` в настройках drain; отключить sticky-сессии на период drain; переключиться на TCP-drain.

### Ошибка лицензий при 2x capacity
- **Сценарий:** Blue и Green вместе превышают лимит лицензий ПО (например, JBoss, WebLogic).
- **Решение:** Планировать capacity с запасом под одну среду +burst; использовать лицензии с гранулярной (per-core) моделью.

### Config drift в Golden Image
- **Сценарий:** Образ содержит ручные правки, не отраженные в Packer/Ansible.
- **Решение:** Ребейк образа по расписанию; все изменения только через IaC; включить проверку `ansible-lint` в CI для плейбуков образа.

---

## Лучшие практики

### Безопасность (Zero Trust & DevSecOps)
- **JIT Access (Just-in-Time):** Полный отказ от постоянно открытых SSH-портов. Доступ предоставляется временно через IAP-прокси или системы типа **Teleport**.
- **Runtime Attestation:** Использование **Keylime** или **Spiffe/Spire** для проверки целостности ноды и выдачи динамических сертификатов только доверенным хостам.
- **Micro-segmentation:** Настройка локальных файрволов (nftables/firewalld) через IaC для ограничения трафика между сервисами внутри сегмента Bare Metal.
- **Ротация секретов:** короткоживущие токены Vault; никогда не хранить статические пароли в инвентаре Ansible (использовать `community.hashi_vault`).

### Мониторинг и Observability
- **Node Exporter & eBPF:** Сбор не только базовых метрик (CPU/RAM), но и детальной статистики по системным вызовам и сетевым задержкам через eBPF-экспортеры.
- **Log Aggregation:** Использование **Vector** или **Fluent-bit** для сбора логов `journald` и передачи их в централизованное хранилище (Loki/Elastic).

### FinOps и Green Ops
- **Экономическая эффективность:** Автоматическое выключение тестовых VM в нерабочее время и использование Spot-инстансов для пакетной обработки данных.
- **Sustainability:** Мониторинг метрик энергопотребления через **Scaphandre** или IPMI для расчета углеродного следа (Carbon Footprint) инфраструктуры.

### Эксплуатационные практики (Change Management)
- **Runbook и окно обслуживания:** каждый деплой сопровождается документированным планом отката.
- **Soak-период:** держите старую версию в резерве минимум до прохождения пика нагрузки после switch.
- **Тестирование отката:** процедура возврата проверяется не реже, чем сам деплой (LVM-снимок, symlink-flip, VRRP-priority).
- **Гигиена Golden Image:** ребейк образов по расписанию (патчи безопасности), строгое версионирование; не копить ручные правки внутри «золотого» образа.
- **Резервирование ёмкости:** под Rolling нужен минимум N+1, под Blue-Green — 2x ресурсов (учитывайте лимиты лицензий ПО).

---

## Граничные случаи и ограничения

- **Legacy-приложения без горизонтального масштабирования:** не поддерживают несколько инстансов одновременно — допустим только in-place restart (простой неизбежен) либо окно обслуживания; Blue-Green/Canary к ним неприменимы напрямую.
- **Stateful и СУБД:** нельзя держать две версии приложения с расходящимися схемами без паттерна **Expand-Contract**; миграция БД отделяется от деплоя приложения и выполняется в обратно-совместимом виде.
- **Лицензии:** удвоение сред (Blue-Green, 2x capacity) может нарушать лицензионные лимиты ПО — уточняйте before planning.
- **Общие хранилища (NFS/iSCSI):** при переключении обе среды видят одни данные — риск гонок и повреждения; изолируйте через per-instance пути или read-only монтирование для Green до cutover.
- **Аппаратная неоднородность:** разные CPU/ядра между узлами батча → закрепление (pinning), проверка `lscpu`; NUMA-аффинитет для чувствительных к задержкам сервисов.
- **Дрифт прошивки/BIOS:** между серверами одного пула → включать проверку версий firmware в ZTP и принудительный апгрейд через Redfish/IPMI.
- **Long-lived соединения (WebSocket/SSE/БД-пулы):** при переносе VIP или веса in-flight соединения к старой среде разрываются; требуется connection draining и клиентский reconnect.

---

## Дополнительная информация

### См. также

- **[Сравнение стратегий развертывания](./comparison.md)** — матрица выбора стратегии и применимость в традиционной среде.
- **[Health Checks и Rollback](./deployment_health_checks_and_rollback.md)** — методы автоматической проверки и отката после деплоя.
- **[Ansible: лучшие практики безопасности](../../Ansible/ansible_security_best_practices.md)** — управление секретами, ролями и JIT-доступом.
