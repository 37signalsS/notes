# Установка Prometheus через APT

## Определения

**Установка через APT** — метод развертывания Prometheus и его компонентов на дистрибутивах Linux на базе Debian (включая Ubuntu) с использованием стандартного пакетного менеджера `apt`.

*   **Prometheus Server**: основной сервис сбора и хранения метрик. В репозиториях поставляется как пакет `prometheus`.
*   **Node Exporter**: агент для мониторинга ресурсов хоста. Поставляется как пакет `prometheus-node-exporter`.
*   **Alertmanager**: сервис обработки и маршрутизации алертов. Поставляется как пакет `prometheus-alertmanager`.
*   **Pushgateway**: сервис-посредник для сбора метрик от короткоживущих задач. Поставляется как пакет `prometheus-pushgateway`.
*   **PPA (Personal Package Archive)**: сторонний репозиторий для Ubuntu, используемый для получения свежих версий ПО, недоступных в официальных репозиториях.
*   **apt-mark hold**: команда, фиксирующая текущую версию пакета, чтобы предотвратить её автоматическое обновление при `apt upgrade`.
*   **apt-cache policy**: команда для просмотра приоритетов источников и доступных версий пакета во всех подключенных репозиториях.
*   **systemd drop-in override**: файл в `/etc/systemd/system/<service>.service.d/`, переопределяющий параметры unit-файла без изменения исходного файла из пакета.

## Основные концепции

### Преимущества пакетной установки

1.  **Автоматизация**: Пакеты автоматически настраивают `systemd` unit-файлы (располагаются в `/lib/systemd/system/`), создают системного пользователя `prometheus` и настраивают ротацию логов через `logrotate`.
2.  **Безопасность**: Обновления безопасности интегрированы в общий цикл обновления системы (`apt upgrade`).
3.  **Стандартная иерархия путей**:
    *   **Конфигурация**: `/etc/prometheus/prometheus.yml`
    *   **Флаги запуска**: `/etc/default/prometheus` (для среды выполнения) и `/lib/systemd/system/prometheus.service` (unit-файл)
    *   **Данные (TSDB)**: `/var/lib/prometheus/`
    *   **Исполняемые файлы**: `/usr/bin/prometheus`
4.  **Управление конфигурационными файлами (conffiles)**: Пакеты APT помечают пользовательские конфиги как `conffiles`. При обновлении пакет предлагает сохранить текущую версию или заменить на новую. Всегда выбирайте сохранение текущей версии, если вы вносили ручные изменения.

### Структура пакета APT

Пакет `prometheus` разбит на логические компоненты:
*   `prometheus` — сервер, бинарный файл, unit-файл, базовый конфиг.
*   `prometheus-node-exporter` — экспортер метрик хоста.
*   `prometheus-alertmanager` — сервис алертинга.
*   `prometheus-pushgateway` — шлюз для push-метрик.

Установка через `apt install -y prometheus prometheus-node-exporter` тянула зависимости и создавала все необходимые директории с правами `prometheus:prometheus`.

### Особенности управления версиями

Официальные репозитории Debian и Ubuntu часто содержат устаревшие версии (например, ветку 2.x, когда актуальна 3.x).
*   **Фиксация версии**: Чтобы избежать нежелательного обновления при `apt upgrade`, используйте команду `apt-mark hold`.
*   **Конфликты конфигурации**: При обновлении пакета APT может спросить, оставить ли ваш `prometheus.yml` или заменить его версией из пакета. Всегда выбирайте сохранение текущей версии (`N` или `O`).
*   **Просмотр доступных версий**: Используйте `apt-cache policy prometheus`, чтобы увидеть, какие версии доступны в подключенных репозиториях и из какого источника они будут установлены.

### Сравнение методов установки

| Метод | Контроль версий | Сложность | Сценарий |
| :--- | :--- | :--- | :--- |
| **Официальные репозитории Debian/Ubuntu** | Низкий (версия определяется дистрибутивом) | Низкая | Тестовые среды, где приоритет — стабильность и автоматическое обновление |
| **PPA prometheus-community** | Средний (свежие версии, но не guaranteed) | Низкая | Получение Prometheus 3.0+ на старых версиях ОС |
| **Локальный репозиторий (aptly / file-based)** | Высокий (фиксируете конкретные DEB) | Средняя | Production, air-gapped среды, compliance |

## Практические сценарии

### Сценарий 1: Базовая установка из официальных репозиториев

Подходит для стабильных систем, где приоритетом является совместимость, а не новые функции.

```bash
# 1. Обновление локального индекса пакетов
sudo apt update

# 2. Установка сервера и базового экспортера
sudo apt install -y prometheus prometheus-node-exporter
# → [OK] Installed prometheus, prometheus-node-exporter

# 3. Проверка автоматического запуска сервисов
sudo systemctl is-active prometheus
# → active
```

### Сценарий 2: Установка свежих версий через PPA (Ubuntu)

Рекомендуется для получения Prometheus 3.0+ на старых версиях ОС.

> **Примечание:** PPA `prometheus-community` поддерживается сообществом. Для production сред рассмотрите использование локального репозитория (Сценарий 7) или бинарной установки для максимального контроля над версиями.

```bash
# 1. Добавление репозитория сообщества
sudo add-apt-repository ppa:prometheus-community/ppa -y

# 2. Обновление и установка
sudo apt update && sudo apt install -y prometheus
# → [OK] Upgraded to latest community version

# 3. Проверка версии
prometheus --version
# → prometheus, version 3.x.x ...
```

### Сценарий 3: Фиксация версии (Pinning)

Предотвращает автоматическое обновление Prometheus, которое может привести к несовместимости конфигурации.

```bash
# Фиксация текущей версии
sudo apt-mark hold prometheus prometheus-node-exporter
# → prometheus set on hold.
# → prometheus-node-exporter set on hold.

# Снятие фиксации для планового обновления
sudo apt-mark unhold prometheus
# → prometheus placed on hold.
```

### Сценарий 4: Кастомизация параметров запуска

Используйте **systemd drop-in override** вместо прямого редактирования `/etc/default/prometheus`, так как файл из пакета может быть перезаписан при обновлении.

```bash
# Создание override-директории
sudo mkdir -p /etc/systemd/system/prometheus.service.d

# Создание файла с переопределениями
sudo tee /etc/systemd/system/prometheus.service.d/override.conf <<EOF
[Service]
Environment="ARGS=--storage.tsdb.retention.time=30d --web.enable-lifecycle --web.listen-address=127.0.0.1:9090"
EOF

# Перезагрузка systemd и применение изменений
sudo systemctl daemon-reload
sudo systemctl restart prometheus

# Проверка применяемых параметров
systemctl show prometheus --property=Environment
# → Environment=ARGS=--storage.tsdb.retention.time=30d ...
```

### Сценарий 5: Настройка межсетевого экрана (UFW)

```bash
# Разрешить доступ к UI (порт 9090) только из доверенной подсети
sudo ufw allow from 10.0.0.0/24 to any port 9090 proto tcp comment 'Prometheus UI'

# Разрешить сбор метрик сервером с агента (порт 9100)
sudo ufw allow from <IP_SERVER> to any port 9100 proto tcp comment 'Node Exporter'
# → Rules updated

# Проверка статуса
sudo ufw status numbered
```

### Сценарий 6: Установка Alertmanager и Pushgateway через APT

```bash
# Установка полного стека мониторинга
sudo apt update && sudo apt install -y \
  prometheus \
  prometheus-node-exporter \
  prometheus-alertmanager \
  prometheus-pushgateway

# Проверка статуса всех сервисов
systemctl is-active prometheus alertmanager pushgateway
# → active
# → active
# → active
```

### Сценарий 7: Air-gapped установка через локальный APT-репозиторий

Для сред без доступа к интернету подготовьте все DEB-пакеты и метаданные на машине с выходом в сеть, затем перенесите на изолированный хост.

```bash
# На машине с интернетом: создание локального репозитория с помощью aptly
sudo apt update && sudo apt install -y aptly
aptly mirror create noble-main http://archive.ubuntu.com/ubuntu/ noble main
aptly mirror update noble-main
aptly repo create prometheus-local

# Импорт DEB-пакетов Prometheus (скачаны вручную с GitHub)
aptly package import prometheus-local prometheus_*.deb prometheus-node-exporter_*.deb

# Фиксация snapshot и публикация
aptly snapshot create prometheus-stable from repo prometheus-local
aptly publish snapshot -distribution="noble" prometheus-stable

# Экспорт репозитория на USB/NFS
# На изолированном хосте: добавление локального репозитория
sudo tee /etc/apt/sources.list.d/prometheus-local.list <<EOF
deb [trusted=yes] file:/mnt/prometheus-local noble main
EOF
sudo apt update && sudo apt install -y prometheus
```

> **Примечание:** Для автоматического зеркалирования всей цепочки зависимостей используйте `apt-mirror` или `reposync`. Подробные стратегии изолированной синхронизации описаны в **[Изолированные среды (Air-gapped)](../../CI-CD/Core_Concepts/air_gapped_environments.md)**.

### Сценарий 8: Upgrade и Rollback для APT

Плановое обновление с возможностью отката к предыдущей стабильной версии.

```bash
# 1. Просмотр текущей и доступной версий
apt-cache policy prometheus
# → Installed: 3.13.2
# → Candidate: 3.13.3

# 2. Создание резервной копии конфигурации
sudo cp -a /etc/prometheus /etc/prometheus.bak.$(date +%F)

# 3. Плановое обновление
sudo apt update && sudo apt install --only-upgrade prometheus

# 4. Валидация конфигурации (необходима перед перезапуском)
sudo promtool check config /etc/prometheus/prometheus.yml
# → SUCCESS: /etc/prometheus/prometheus.yml is valid

# 5. Применение изменений
sudo systemctl restart prometheus

# --- ОТКАТ ---
# Если обновление сломало функциональность:
sudo apt-mark unhold prometheus
sudo apt install prometheus=3.13.2

# Восстановление конфигурации (если пакет перезаписал conffiles)
sudo cp -a /etc/prometheus.bak.2026-09-17/* /etc/prometheus/
sudo systemctl restart prometheus
```

> **Важно:** Семейство команд `apt` кэширует локально последние загруженные пакеты. Если нужная версия отсутствует в кэше, настройте локальное зеркало (Сценарий 7) или сохраните DEB-файл вручную. Подробнее: **[Проверки здоровья и откат развертывания](../../CI-CD/Deployment_Strategies/deployment_health_checks_and_rollback.md)**.

### Сценарий 9: Установка через Ansible

Идемпотентный плейбук для автоматической установки стека мониторинга.

```yaml
---
- name: Установка Prometheus через APT
  hosts: monitoring
  become: yes
  vars:
    prometheus_version: "3.13.2"
    prometheus_components:
      - prometheus
      - prometheus-node-exporter
      - prometheus-alertmanager
      - prometheus-pushgateway

  tasks:
    - name: Обновление кеша APT
      ansible.builtin.apt:
        update_cache: yes
        cache_valid_time: 3600

    - name: Добавление PPA (опционально, для Ubuntu)
      ansible.builtin.apt_repository:
        repo: "ppa:prometheus-community/ppa"
        state: present
        update_cache: yes
      when: ansible_distribution == 'Ubuntu'

    - name: Установка пакетов Prometheus
      ansible.builtin.apt:
        name: "{{ item }}={{ prometheus_version }}"
        state: present
        allow_downgrade: yes
        lock_timeout: 120
      register: apt_result
      until: apt_result is success
      retries: 3
      delay: 10
      loop: "{{ prometheus_components }}"

    - name: Фиксация версий (pinning)
      ansible.builtin.command: apt-mark hold {{ item }}
      loop: "{{ prometheus_components }}"

    - name: Создание override для systemd (retention 30d)
      ansible.builtin.copy:
        dest: /etc/systemd/system/prometheus.service.d/override.conf
        content: |
          [Service]
          Environment="ARGS=--storage.tsdb.retention.time=30d --web.enable-lifecycle"
        owner: root
        mode: '0644'
      notify: daemon-reload

    - name: Запуск и включение сервисов
      ansible.builtin.systemd:
        name: "{{ item }}"
        state: started
        enabled: yes
        daemon_reload: yes
      loop: "{{ prometheus_components }}"

  handlers:
    - name: daemon-reload
      ansible.builtin.systemd:
        daemon_reload: yes
```

> **Примечание:** Полное описание модулей управления пакетами доступно в **[Ansible: Модули управления пакетами](../../Ansible/Modules/ansible_package_management_modules.md)**.

### Сценарий 10: Post-install Hardening для APT-установки

После базовой установки выполните проверки, специфичные для пакетной установки.

```bash
# 1. Проверка unit-файла, созданного пакетом APT
systemctl cat prometheus
# → /lib/systemd/system/prometheus.service

# 2. Проверка hardening-директив (должны присутствовать)
systemctl show prometheus --property=NoNewPrivileges,ProtectSystem,ProtectHome,PrivateTmp
# → NoNewPrivileges=yes
# → ProtectSystem=full
# → ProtectHome=yes
# → PrivateTmp=yes

# 3. Проверка прав на директории
namei -l /etc/prometheus/prometheus.yml
namei -l /var/lib/prometheus
# → /etc/prometheus/prometheus.yml prometheus prometheus rw-
# → /var/lib/prometheus prometheus prometheus rwx

# 4. Ограничение слушаемого интерфейса (если не настроено через ARGS)
sudo sed -i 's/^ExecStart=\/usr\/bin\/prometheus/ExecStart=\/usr\/bin\/prometheus --web.listen-address=127.0.0.1:9090/' \
  /lib/systemd/system/prometheus.service
sudo systemctl daemon-reload && sudo systemctl restart prometheus

# 5. Проверка firewall
sudo ufw status numbered
# или
sudo iptables -L -n | grep 9090
```

> **Важно:** Не редактируйте `/lib/systemd/system/prometheus.service` напрямую — используйте drop-in override (Сценарий 4), так как пакетный менеджер может перезаписать исходный файл при обновлении.

Полное руководство по безопасности: **[Безопасность Prometheus](../security.md)**.

## Диагностика и отладка

### Типичные ошибки APT

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `E: Unable to locate package prometheus` | Репозиторий не добавлен или `apt update` не выполнен | Выполните `sudo apt update` или проверьте `/etc/apt/sources.list.d/` |
| `GPG error: ... The following signatures couldn't be verified` | Отсутствует GPG-ключ репозитория | Импортируйте ключ: `curl -fsSL https://packages.prometheus.com/...` |
| `E: Could not get lock /var/lib/dpkg/lock` | Фоновый процесс (unattended-upgrades) блокирует dpkg | Остановите процесс или используйте `retries` + `delay` в Ansible |
| `dpkg: error processing package prometheus (--configure)` | Конфликт conffiles | Выберите сохранение текущей конфигурации (`N`), затем выполните `dpkg --configure -a` |

### Инструменты диагностики

При сбое запуска (`code=exited, status=1`) используйте следующие инструменты:

1.  **Проверка синтаксиса YAML**:
    ```bash
    promtool check config /etc/prometheus/prometheus.yml
    # → SUCCESS: /etc/prometheus/prometheus.yml is valid
    ```
2.  **Анализ логов через journald**:
    ```bash
    # Просмотр последних 50 строк лога
    sudo journalctl -u prometheus -n 50 --no-pager
    # → Мониторинг логов в реальном времени
    sudo journalctl -u prometheus -f
    ```
3.  **Проверка прав доступа**:
    Убедитесь, что директория данных принадлежит пользователю `prometheus`:
    ```bash
    ls -ld /var/lib/prometheus
    # → drwxr-xr-x prometheus prometheus ...
    ```
4.  **Проверка firewall**:
    ```bash
    sudo ufw status numbered
    # или
    sudo iptables -L -n | grep 9090
    sudo nft list ruleset | grep 9090
    ```

### См. также

*   **[Установка Prometheus: обзор](./overview.md)** — архитектурные отличия методов установки, air-gapped и hardening.
*   **[Безопасность Prometheus](../security.md)** — TLS, Basic Auth, сетевые политики и post-install hardening.
*   **[Node Exporter: установка](./node_exporter_installation.md)** — детальная настройка системного агента.
*   **[Nginx Reverse Proxy](./nginx_reverse_proxy.md)** — TLS termination и Basic Auth перед Prometheus.
*   **[Capacity Planning](./capacity_planning.md)** — формулы расчёта ресурсов.
