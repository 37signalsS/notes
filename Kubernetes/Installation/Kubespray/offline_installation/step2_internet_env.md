# Kubespray: Offline установка — Шаг 2: Подготовка окружения на машине с интернетом

## Определения

**pc-inet** — узел с доступом к интернету, выполняющий роль станции сбора (Gateway). Используется для предварительной загрузки всех артефактов Kubespray (образы контейнеров, бинарные файлы, Helm-чарты) и формирования архивов для переноса в закрытую сеть. В сценарии это `192.168.1.99` (Ubuntu 24.04 LTS).

**download_localhost** — специальный параметр Ansible в Kubespray, который заставляет систему загружать все внешние зависимости на управляющую машину (Ansible Control Node, в данном сценарии — pc-inet) вместо того, чтобы пытаться скачать их на целевые узлы кластера. Это ключевой параметр для offline-режима: он позволяет собрать все артефакты в локальном кэше для последующей упаковки.

**Артефакты (Artifacts)** — полный набор внешних зависимостей, необходимых для успешного развертывания без интернета. Классифицируются на несколько групп:
- **Python Wheel пакеты:** зависимости Ansible и плагинов (из `requirements.txt`).
- **System Binaries:** `kubeadm`, `kubectl`, `kubelet`, `etcd`, `helm`, `cni-plugins`, `crictl`, `nerdctl`.
- **Container Images:** системные компоненты Kubernetes (apiserver, scheduler, controller-manager, proxy), сетевые плагины (Cilium, Hubble), системные аддоны (CoreDNS, Local Path Provisioner, Metrics Server).
- **OCI Artifacts:** Helm-чарты, упакованные в формате контейнерных слоев (например, `cilium-1.19.6.tgz`).

**Download Tag** — специальный тег Ansible (`--tags download`), который запускает только этап загрузки артефактов без развёртывания кластера. В связке с `--skip-tags upload,upgrade` позволяет скачать все зависимости в локальный кэш на pc-inet без попытки установки на целевые узлы.

**Температурный инвентарь (Temporary Inventory)** — конфигурация Ansible, в которой все группы кластера (master, node, etcd, calico-rr) указывают на один и тот же IP-адрес pc-inet (`192.168.1.99`). Это «трюк», позволяющий Kubespray «думать», что он настраивает кластер на этой машине, и сохранять все скачанные артефакты локально.

**Python Virtual Environment (venv)** — изолированное окружение Python, предотвращающее конфликты зависимостей между системными пакетами и Ansible. Kubespray требует Python 3.10+ и определённые библиотеки (`jinja2`, `pyyaml`, `jsonschema`), которые устанавливаются из `requirements.txt`.

---

## Основные концепции

### Цель этапа

Создание автономного бандла (bundle), содержащего 100% необходимых ресурсов. Ошибка или отсутствие даже одного образа на этом этапе приведет к сбою установки в закрытом контуре. Этот этап является точкой невозврата: после переноса архивов в закрытую сеть исправление ошибок загрузки требует повторного доступа к интернету.

**Ключевые группы ресурсов:**

- **Python-окружение:** все зависимости из `requirements.txt` для корректной работы Ansible. Включает `ansible-core`, `jinja2`, `pyyaml`, `jsonschema`, `cryptography` и другие.
- **Инфраструктурные бинарные файлы:** `kubeadm`, `kubectl`, `kubelet`, `helm`, `etcd`, `cni-plugins`, `crictl`, `nerdctl`. Версии определяются переменными в `group_vars` (подробности в **[Версиях компонентов](./offline_definitions.md#версии-компонентов-базовый-гайд)**).
- **Контейнерные образы:** образы Kubernetes (apiserver, scheduler, controller-manager, proxy, etcd), сетевые плагины (Cilium, Hubble), системные аддоны (CoreDNS, Local Path Provisioner).
- **Helm-чарты:** шаблоны для развертывания Cilium и других компонентов через Helm-контроллер.

### Структура директорий на pc-inet

На узле `pc-inet` используется стандартизированная структура директорий для упрощения последующей упаковки:

```text
/opt/
├── kuber_off/              # Корневая директория проекта
│   ├── venv/               # Python venv (исключается из git-репозитория)
│   └── kubespray/          # Исходный код Kubespray (git clone)
├── kubespray-cache/        # Локальный кэш артефактов (создается автоматически)
│   ├── images/             # Образы контейнеров в формате .tar
│   └── kubeadm-v*          # Бинарные файлы K8s
└── kubespray-releases/     # Дополнительные инструменты (helm, nerdctl, cilium chart)
```

**Важно:** Директории `kubespray-cache` и `kubespray-releases` создаются автоматически при первом запуске download-тега. Не создавайте их вручную — Kubespray управляет их содержимым.

### Почему pc-inet используется как «фейковый кластер»

Основная проблема offline-развёртывания: Kubespray разработан для развёртывания на реальных узлах. В offline-сценарии реальные узлы (master-1..3, node-1..2) не имеют доступа к интернету. Решение — **температурный инвентарь**:

1. Все IP-адреса в `inventory.ini` указывают на pc-inet (`192.168.1.99`).
2. Kubespray «думает», что настраивает кластер из 7 узлов (7 копий master-1, 7 копий node-1 и т.д.).
3. Благодаря `download_localhost: true` все артефакты сохраняются **локально** на pc-inet, а не отправляются на целевые узлы.
4. После загрузки архивы переносятся в закрытый контур, где Kubespray повторно использует их для реального развёртывания.

Этот подход исключает необходимость настройки сложных прокси или зеркал на pc-inet.

### Механизм download-тега

Kubespray использует систему тегов Ansible для управления запуском отдельных этапов. Download-тег (`--tags download`) запускает только плейбуки загрузки:

- `download.yml` — основной плейбук загрузки артефактов.
- `download/` — роль, определяющая параметры загрузки (зеркала, формат, лимиты).

Параметры `--skip-tags upload,upgrade` исключают:
- `upload` — попытку загрузки артефактов на целевые узлы (в offline-режиме не нужна).
- `upgrade` — обновление существующих компонентов (при первой установке не требуется).

### Требования к ресурсам и времени

| Параметр | Значение | Примечание |
| :--- | :--- | :--- |
| **Дисковое пространство** | 15-25 ГБ свободного места в `/opt` | Зависит от количества образов и версий |
| **Время загрузки** | 15-40 минут | Зависит от скорости интернет-канала |
| **Скорость интернета** | Рекомендуется >10 Мбит/с | Некоторые образы (Cilium) >500 МБ |
| **Сеть** | Доступ к gcr.io, docker.io, quay.io, github.com, helm.cilium.io | Проверьте DNS и файрвол |

**Мониторинг места на диске:**
```bash
watch -n 30 'du -sh /opt/kubespray-cache /opt/kubespray-releases 2>/dev/null'
# → Обновляется каждые 30 секунд, показывает рост кэша
```

### Доступные реестры

Для успешной загрузки pc-inet должен иметь доступ к следующим реестрам:

| Реестр | Использование | Типичные образы |
| :--- | :--- | :--- |
| `registry.k8s.io` | Kubernetes core | kube-apiserver, kube-scheduler, etcd, coredns |
| `gcr.io` | Google Container Registry | kube-proxy, kube-controller-manager |
| `docker.io` | Docker Hub | редко (coredns,一些 аддоны) |
| `quay.io` | Red Hat Quay | Cilium, Hubble, MetalLB |
| `helm.cilium.io` | OCI Helm-репозиторий Cilium | cilium chart |

> Если какой-либо реестр недоступен, используйте зеркала или VPN на этапе pc-inet. Подробности в разделе «Типовые ошибки» ниже.

---

## Практические сценарии

### Алгоритм загрузки артефактов

Данный сценарий описывает полный процесс сбора артефактов на узле `pc-inet` (Ubuntu 24.04). Выполняется **один раз** перед переносом в закрытый контур.

#### Шаг 2.1: Подготовка системы и клонирование репозитория

```bash
# Создание корневой директории
sudo mkdir -p /opt/kuber_off && sudo chown $USER:$USER /opt/kuber_off
cd /opt/kuber_off

# Установка зависимостей для Python venv
sudo apt update && sudo apt install python3.12-venv python3-pip git -y
# → python3.12-venv: виртуальные окружения Python
# → git: клонирование репозитория Kubespray

# Создание изолированного окружения Python 3.12
python3.12 -m venv venv
source venv/bin/activate
# → (venv) admin@pc-inet:/opt/kuber_off$

# Проверка версии Python (должна быть 3.12+)
python3 --version
# → Python 3.12.x

# Клонирование стабильной ветки Kubespray (v2.31.0)
git clone --branch v2.31.0 --single-branch https://github.com/kubernetes-sigs/kubespray.git
# → Cloning into 'kubespray'...
# → Checking out files: 100% (2105/2105), done.
```

**Почему `--single-branch`:** Ускоряет клонирование, загружая только нужную ветку (v2.31.0) без истории всех коммитов.

**Валидация:**
```bash
cd /opt/kuber_off/kubespray && git log --oneline -1
# → a]b1c2d3e (HEAD -> v2.31.0) Kubespray v2.31.0 release
```

#### Шаг 2.2: Установка зависимостей и настройка инвентаря

```bash
# Установка Ansible и необходимых библиотек
pip install -r requirements.txt
# → Successfully installed ansible-core-2.17.x jinja2-3.x pyyaml-6.x ...

# Проверка версии Ansible
ansible --version
# → ansible [core 2.17.x]

# Создание директории кластера на основе шаблона
cp -r inventory/sample inventory/offline_cluster
```

**Настройка температурного инвентаря:**

Создайте файл `inventory/offline_cluster/inventory.ini` со следующим содержимым. Все группы указывают на IP pc-inet — это позволяет Kubespray сохранять артефакты локально:

```ini
[all]
pc-inet ansible_host=192.168.1.99

[kube_control_plane]
pc-inet ansible_host=192.168.1.99

[etcd]
pc-inet ansible_host=192.168.1.99

[kube_node]
pc-inet ansible_host=192.168.1.99

[k8s_cluster:children]
kube_control_plane
kube_node
```

> **Важно:** Это временная конфигурация только для этапа загрузки. После переноса архивов в закрытый контур `inventory.ini` будет перезаписан реальными IP-адресами кластера.

**Валидация:**
```bash
# Проверка подключения к pc-inet
ansible -i inventory/offline_cluster/inventory.ini all -m ping
# → pc-inet | SUCCESS => { "changed": false, "ping": "pong" }
```

#### Шаг 2.3: Конфигурация переменных offline-загрузки

Создайте файл `inventory/offline_cluster/group_vars/all/offline.yml` со следующим содержимым:

```yaml
---
# Режим загрузки артефактов на локальную машину
download_run_once: true           # Скачивать файл/образ только один раз
download_localhost: true          # Хранить кэш на управляющей машине
download_format: "tarball"        # Формат архивов для переноса (.tar)

# Пути для сохранения (согласуются со структурой /opt)
local_release_dir: "/opt/kubespray-releases"
download_cache_dir: "/opt/kubespray-cache"

# Версии и специфические настройки (пример для Cilium)
cilium_version: "v1.19.6"
cilium_install_with_helm: true
```

**Параметры объяснены:**
- `download_run_once: true` — при установке на pc-inet образы скачиваются только один раз, а не на каждый узел. Это критично в offline-среде, где повторная загрузка невозможна.
- `download_localhost: true` — бинарные файлы и образы сохраняются локально на pc-inet, а не на целевых узлах. Это позволяет упаковать их в единый архив для переноса.
- `download_format: "tarball"` — образы сохраняются в формате `.tar`, что упрощает ручную загрузку в Harbor через `docker load` и `docker push`.

> Подробный справочник переменных доступен в **[Offline-концепциях: group_vars](./offline_concepts.md#1-справочник-переменных-для-offline-режима)**.

**Валидация:**
```bash
# Проверка создания файла
cat inventory/offline_cluster/group_vars/all/offline.yml
# → Должен содержать download_run_once, download_localhost и download_format
```

#### Шаг 2.4: Запуск процесса загрузки

Этап может занять от 15 до 40 минут в зависимости от скорости интернет-канала и количества компонентов. Рекомендуется запускать в `screen` или `tmux` для обрыва соединения.

```bash
# Запуск в tmux/screen (рекомендуется)
tmux new -s kubespray-download

# Запуск загрузки
ansible-playbook -i inventory/offline_cluster/inventory.ini cluster.yml \
  --tags download \
  --skip-tags upload,upgrade \
  -e "@inventory/offline_cluster/group_vars/all/offline.yml" \
  -b -u admin
# → PLAY RECAP *****************
# → localhost : ok=145 changed=89 unreachable=0 failed=0 ...
```

**Ожидаемый прогресс:**
1. Загрузка Python-пакетов и зависимостей Ansible.
2. Загрузка бинарных файлов (kubeadm, kubectl, kubelet, etcd, helm, cni-plugins).
3. Загрузка контейнерных образов (~30-50 образов, ~5-10 ГБ).
4. Сохранение в `/opt/kubespray-cache/images/` и `/opt/kubespray-releases/`.

**Мониторинг.progress:**
```bash
# В отдельном терминале
watch -n 10 'ls /opt/kubespray-cache/images/*.tar 2>/dev/null | wc -l'
# → Показывает количество загруженных образов
```

**Валидация после загрузки:**
```bash
# Проверка наличия критических образов
ls /opt/kubespray-cache/images/*.tar | wc -l
# → Ожидаемый результат: >50 файлов

# Проверка наличия бинарных файлов
ls /opt/kubespray-releases/
# → Ожидаемый результат: helm, cilium-1.19.6.tgz, nerdctl, ...

# Проверка размера кэша
du -sh /opt/kubespray-cache /opt/kubespray-releases
# → /opt/kubespray-cache: ~5-10 ГБ
# → /opt/kubespray-releases: ~500 МБ - 1 ГБ
```

#### Шаг 2.5: Ручная загрузка дополнительных компонентов

Некоторые специфические ресурсы (Helm-чарты и дополнительные утилиты) надежнее скачать вручную.

**Установка Helm (если не был скачан автоматически):**
```bash
# Проверка наличия helm в /opt/kubespray-releases/
ls /opt/kubespray-releases/helm 2>/dev/null && echo "Helm найден" || echo "Helm не найден — скачайте вручную"

# Если helm не найден — скачайте вручную:
HELM_VERSION="v3.16.3"
curl -Lo /opt/kubespray-releases/helm https://get.helm.sh/helm-${HELM_VERSION}-linux-amd64
chmod +x /opt/kubespray-releases/helm
# → Проверка: /opt/kubespray-releases/helm version
```

**Загрузка Helm-чарта Cilium:**
```bash
# Добавление официального репозитория Cilium
helm repo add cilium https://helm.cilium.io
# → "cilium" has been added to your repositories

helm repo update
# → Hang tight while we grab the latest from your chart repositories...

# Скачивание чарта (версия должна совпадать с cilium_version в offline.yml)
helm pull cilium/cilium --version 1.19.6
# → /opt/kuber_off/kubespray/cilium-1.19.6.tgz

# Перемещение в директорию релизов
mv cilium-1.19.6.tgz /opt/kubespray-releases/
# → Проверка: ls /opt/kubespray-releases/cilium-1.19.6.tgz
```

> Подробный процесс публикации чарта в Harbor описан в **[Offline-концепциях: Публикация Helm-чарта Cilium](./offline_concepts.md#3-публикация-helm-чарта-cilium-v-harbor)**.

**Полный список артефактов для проверки:**
```bash
echo "=== Бинарные файлы ==="
ls /opt/kubespray-releases/
# → Ожидается: helm, cilium-1.19.6.tgz, nerdctl, kubeadm, kubectl, kubelet, ...

echo "=== Образы контейнеров ==="
ls /opt/kubespray-cache/images/*.tar | head -20
# → Ожидается: kube-apiserver, kube-scheduler, etcd, coredns, cilium, hubble, ...

echo "=== Количество образов ==="
ls /opt/kubespray-cache/images/*.tar | wc -l
# → Ожидается: >50
```

#### Шаг 2.6: Формирование финальных архивов

После завершения всех проверок упакуйте данные для физического переноса (на USB или через SCP).

```bash
# Упаковка исходного кода Kubespray (включая venv)
tar -C /opt -czf kubespray-code.tar.gz kuber_off
# → Включает: исходный код Kubespray, Python venv, inventory/offline_cluster

# Упаковка кэша и бинарных файлов
tar -C /opt -czf kubespray-offline-bundle.tar.gz \
  kubespray-cache kubespray-releases
# → Включает: все образы (.tar), бинарные файлы, Helm-чарты
```

**Проверка размера архивов:**
```bash
du -sh /opt/*.tar.gz
# → kubespray-code.tar.gz: ~200-500 МБ
# → kubespray-offline-bundle.tar.gz: ~5-15 ГБ
# → Общий объем: ~5-16 ГБ
```

**Проверка целостности архивов:**
```bash
# Проверка tar-архивов на ошибки
tar -tzf /opt/kubespray-code.tar.gz > /dev/null && echo "kubespray-code.tar.gz: OK" || echo "kubespray-code.tar.gz: ОШИБКА"
tar -tzf /opt/kubespray-offline-bundle.tar.gz > /dev/null && echo "kubespray-offline-bundle.tar.gz: OK" || echo "kubespray-offline-bundle.tar.gz: ОШИБКА"
```

**Перенос архивов в закрытый контур:**

Способ 1 — SCP (если есть сетевая доступность):
```bash
# С pc-inet на master-1 (внутренняя сеть)
scp /opt/kubespray-code.tar.gz admin@192.168.1.101:~/
scp /opt/kubespray-offline-bundle.tar.gz admin@192.168.1.101:~/
# → Проверьте скорость передачи: ~100 МБ/с через локальную сеть
```

Способ 2 — USB-накопитель (если нет сетевой доступности):
```bash
# Копирование на USB
sudo mount /dev/sdb1 /mnt/usb
cp /opt/kubespray-code.tar.gz /mnt/usb/
cp /opt/kubespray-offline-bundle.tar.gz /mnt/usb/
sudo umount /mnt/usb
# → На master-1 распакуйте: tar -xzf ~/kubespray-offline-bundle.tar.gz -C /opt/
```

---

## Дополнительная информация

### Типовые ошибки и решения

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `ERROR! the role 'xxx' was not found` | Не установлены зависимости Ansible | `pip install -r requirements.txt` |
| `python3-apt` missing | Python venv не имеет доступа к системным пакетам | `python3.12 -m venv --system-site-packages venv` или `pip install python-apt` |
| `403 Forbidden` при скачивании | Реестр блокирует запросы ( rate limiting, geo-blocking) | Используйте зеркала (mirror.gcr.io) или VPN на pc-inet |
| `No space left on device` | Недостаточно места в `/opt` | Очистите старые файлы: `docker system prune -a` или `rm -rf /opt/kubespray-cache/images/*.tar` |
| `Connection refused` к gcr.io | DNS не резолвит или файрвол блокирует | Проверьте DNS: `nslookup gcr.io`, добавьте правила файрвола |
| `helm: command not found` | Helm не скачан автоматически | Скачайте вручную (шаг 2.5) или проверьте `/opt/kubespray-releases/helm` |
| `PLAY RECAP ... failed=1` | Ошибка в одном из плейбуков | Проверьте лог: `ansible-playbook ... -vvv` для детального вывода |
| Образы не скачаны частично | Network timeout при скачивании больших образов | Повторите запуск — `download_run_once` пропустит уже скачанные файлы |

### Диагностика сетевой доступности

Перед запуском загрузки убедитесь, что pc-inet имеет доступ ко всем необходимым реестрам:

```bash
# Проверка DNS-резолва
for registry in registry.k8s.io gcr.io docker.io quay.io helm.cilium.io github.com; do
  nslookup $registry > /dev/null 2>&1 && echo "$registry: DNS OK" || echo "$registry: DNS FAILED"
done

# Проверка HTTP-доступа
for registry in registry.k8s.io gcr.io docker.io quay.io; do
  curl -s -o /dev/null -w "%{http_code}" https://$registry/v2/ && echo " $registry: HTTP OK" || echo " $registry: HTTP FAILED"
done
# → Ожидаемый результат: все реестры отвечают 200 или 401 (Unauthorized — нормально)
```

### Оптимизации для загрузки

- **Зеркала реестров:** если основной реестр недоступен, настройте зеркала в `group_vars` (например, `mirror.gcr.io` для gcr.io).
- **Параллельная загрузка:** Kubespray автоматически использует несколько потоков. Увеличьте `download_concurrent` в `ansible.cfg` для ускорения.
- **Инкрементальная загрузка:** если загрузка прервалась, повторный запуск с теми же параметрами пропустит уже скачанные файлы (благодаря `download_run_once`).
- **Очистка кэша:** перед повторной загрузкой очистите старые файлы: `rm -rf /opt/kubespray-cache/images/*.tar`.

### Проверка полноты загрузки

Перед упаковкой архивов убедитесь, что все критические компоненты скачаны:

```bash
#!/bin/bash
echo "--- ПРОВЕРКА ПОЛНОТЫ ЗАГРУЗКИ ---"

# 1. Бинарные файлы
for bin in kubeadm kubectl kubelet helm; do
  if [ -f "/opt/kubespray-releases/$bin" ]; then
    echo "[OK] $bin найден"
  else
    echo "[FAIL] $bin отсутствует!"
  fi
done

# 2. Образы Kubernetes
for img in kube-apiserver kube-scheduler kube-controller-manager kube-proxy etcd coredns; do
  if ls /opt/kubespray-cache/images/*${img}*.tar > /dev/null 2>&1; then
    echo "[OK] $img найден"
  else
    echo "[FAIL] $img отсутствует!"
  fi
done

# 3. Cilium
if ls /opt/kubespray-releases/cilium-*.tgz > /dev/null 2>&1; then
  echo "[OK] Cilium chart найден"
else
  echo "[FAIL] Cilium chart отсутствует!"
fi

# 4. Общее количество образов
img_count=$(ls /opt/kubespray-cache/images/*.tar 2>/dev/null | wc -l)
echo "[INFO] Всего образов: $img_count (ожидается >50)"

echo "--- ПРОВЕРКА ЗАВЕРШЕНА ---"
```

### Чистовая настройка inventory.ini

После переноса архивов в закрытый контур (на master-1) `inventory.ini` должен быть перезаписан реальными IP-адресами кластера. Пример конфигурации:

```ini
[all]
pc-inet   ansible_host=192.168.1.99
harbor    ansible_host=192.168.1.100
master-1  ansible_host=192.168.1.101
master-2  ansible_host=192.168.1.102
master-3  ansible_host=192.168.1.103
node-1    ansible_host=192.168.1.104
node-2    ansible_host=192.168.1.105

[kube_control_plane]
master-1
master-2
master-3

[etcd]
master-1
master-2
master-3

[kube_node]
node-1
node-2

[k8s_cluster:children]
kube_control_plane
kube_node
```

> Подробности по настройке inventory в закрытом контуре — в **[Offline-практиках: Этап 3](./offline_practical.md#этап-3-настройка-harbor-в-закрытом-конуре)**.

### См. также

- **[Шаг 1: Подготовка VM](./step1_vm_preparation.md)** — SSH-доступ и настройка ОС.
- **[Шаг 3: Подготовка закрытого контура](./step3_offline_env.md)** — развертывание Harbor и импорт бандла.
- **[Offline-концепции: group_vars](./offline_concepts.md#1-справочник-переменных-для-offline-режима)** — справочник переменных для offline-режима.
