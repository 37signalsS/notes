# Kubespray: Offline установка — Шаг 3: Подготовка закрытого контура

## Определения

**Локальный реестр (Local Registry)** — сервер внутри изолированной сети, предназначенный для хранения и раздачи контейнерных образов, Helm-чартов и OCI-артефактов без доступа к внешнему интернету. В данном руководстве используется **Harbor** — промышленный реестр с поддержкой OCI, RBAC, веб-интерфейса и журналирования.

**Harbor** — open-source реестр контейнеров, расширяющий функциональность Docker Registry добавлением управления проектами (namespaces), контроля доступа, сканирования уязвимостей, журналирования и веб-интерфейса. Версия v2.11+ рекомендуется для совместимости с Kubespray. Harbor является единственной точкой доступа к образам в offline-среде — его недоступность полностью блокирует установку и обновление кластера.

**Проект (Project)** — логический контейнер в Harbor для группировки образов и чартов. Каждый проект имеет собственные политики доступа (Public/Private), quotas и.notifications. Kubespray требует проект `k8s` (Public) для системных образов и `helm` (Private) для OCI-чартов.

**OCI-артефакты (OCI Artifacts)** — спецификация Open Container Initiative, позволяющая хранить в реестре не только образы, но и другие типы данных, такие как Helm-чарты. Harbor поддерживает OCI-артефакты через проекты с типом_ARTIFACT.

**docker load** — команда для загрузки контейнерных образов из tar-архивов (формат `docker save`) в локальный Docker-движок. Используется на master-1 для импорта артефактов, скачанных на pc-inet.

**docker tag** — команда для создания нового тега (alias) для существующего образа. В offline-сценарии используется для переключения оригинальных тегов на локальные пути в Harbor (например, `registry.k8s.io/kube-apiserver:v1.34.3` → `harbor.domain.local/k8s/registry.k8s.io/kube-apiserver:v1.34.3`).

**docker push** — команда для загрузки образа из локального Docker-движока в реестр. После `docker tag` образ с новым тегом загружается в Harbor, где становится доступен для containerd на всех узлах кластера.

---

## Основные концепции

### Цель этапа

Развёртывание и наполнение базовых сервисов внутри закрытого контура. Этот этап превращает загруженные на Шаге 2 артефакты в доступные для установщика ресурсы. Без Harbor невозможно развёртывание кластера — containerd на каждом узле будет обращаться к Harbor для pull-запросов образов.

**Ключевые задачи:**

1. **Подготовка master-1:** настройка управляющего узла (Ansible Control Node) для работы в закрытом контуре (распаковка артефактов, установка Helm).
2. **Развёртывание Harbor:** создание центрального хранилища образов и чартов на выделенном узле (192.168.1.100).
3. **Миграция образов:** импорт tar-архивов в Docker-движок, автоматизированное тегирование и загрузка образов Kubernetes в локальный реестр.
4. **Публикация Helm-чартов:** размещение чарта Cilium в OCI-репозитории Harbor для последующего использования Helm-контроллером.
5. **Настройка инвентаря:** приведение переменных Ansible к реальности закрытого контура (реальные IP, реестр, registry mapping).

### Почему Harbor, а не Docker Registry

Docker Registry — минимальный реестр без управления проектами, веб-интерфейса и RBAC. Harbor добавляет:

| Функция | Docker Registry | Harbor |
| :--- | :--- | :--- |
| Управление проектами | Нет | Да (namespaces, quotas) |
| Веб-интерфейс | Нет | Да (просмотр, удаление образов) |
| RBAC | Нет | Да (роли, проекты,机器人) |
| OCI-чарты | Нет | Да (Helm charts через OCI) |
| Журналирование | Минимальное | Полное (audit log) |
| Сканирование уязвимостей | Нет | Да (Trivy) |

В offline-среде Harbor является **единственным** источником образов. Его недоступность парализует весь кластер.

### Миграция образов: как работает тегирование

Kubespray формирует полные теги образов, комбинируя `registry_host` с оригинальным путём. Механизм:

```
Оригинальный тег:    registry.k8s.io/kube-apiserver:v1.34.3
Целевой тег в Harbor: harbor.domain.local/k8s/registry.k8s.io/kube-apiserver:v1.34.3
                     ─────── ── ─────────────────────────────
                     Harbor   k8s  Оригинальный путь
                     host   project
```

Containerd на целевом узле через `hosts.toml` перенаправляет pull-запросы `registry.k8s.io` на `harbor.domain.local/k8s/registry.k8s.io`. Это прозрачно для Kubespray и других компонентов.

> Подробный справочник переменных registry mapping доступен в **[Offline-концепциях: group_vars](./offline_concepts.md#12-переопределение-реестров-в-закрытом-конуре)**.

### Требования к ресурсам Harbor

| Параметр | Значение | Примечание |
| :--- | :--- | :--- |
| **CPU** | 2+ ядра | Зависит от нагрузки (pull/push) |
| **RAM** | 4+ ГБ | 8 ГБ рекомендуется |
| **Диск** | 100+ ГБ SSD | SSD обязателен для производительности |
| **Сеть** | Доступен с master-1, всех master и worker | DNS: harbor.domain.local → 192.168.1.100 |

> Подробные требования к узлу harbor приведены в **[Offline-практиках: Инфраструктурный план](./offline_practical.md#инфраструктурный-план-кластера)**.

### Требования к проектам в Harbor

Для корректной работы автоматизации Kubespray в Harbor должны быть созданы следующие логические разделы:

| Проект | Тип доступа | Назначение |
| :--- | :--- | :--- |
| **k8s** | **Публичный (Public)** | Все системные образы (k8s.gcr.io, quay.io, docker.io) |
| **helm** | Приватный (Private) | OCI-репозиторий для хранения Helm-чартов сетевого плагина |

> **Примечание:** Проект `k8s` должен быть публичным, чтобы `containerd` на узлах мог скачивать образы до момента настройки секретов аутентификации. После завершения установки проект можно сделать приватным (см. **[Настройка авторизации](./offline_concepts.md#13-настройка-авторизации-если-проект-k8s-не-public)**).

---

## Практические сценарии

### Алгоритм подготовки закрытого контура

Данный сценарий описывает полный процесс настройки Harbor и миграции образов. Выполняется на узлах `master-1` (Ansible Control Node) и `harbor` (реестр) после переноса архивов с pc-inet.

#### Шаг 3.1: Подготовка управляющего узла (master-1)

Распаковка перенесённых архивов и установка инструментов управления.

```bash
# Распаковка исходного кода и бандла артефактов
tar -xzf ~/kubespray-code.tar.gz -C /opt/
tar -xzf ~/kubespray-offline-bundle.tar.gz -C /opt/
# → /opt/kuber_off/kubespray, /opt/kubespray-cache, /opt/kubespray-releases

# Установка Helm (управление чартами)
sudo cp /opt/kubespray-releases/helm /usr/local/bin/
sudo chmod +x /usr/local/bin/helm

# Установка kubectl (управление кластером)
sudo cp /opt/kubespray-releases/kubectl /usr/local/bin/
sudo chmod +x /usr/local/bin/kubectl
```

**Валидация:**
```bash
helm version
# → version.BuildInfo{Version:"v3.16.x", ...}

kubectl version --client
# → Client Version: v1.34.3

ls /opt/kubespray-cache/images/*.tar | wc -l
# → Ожидаемый результат: >50 файлов
```

**Требования к диску:** Убедитесь, что на master-1 достаточно места для распаковки архивов:
```bash
df -h /opt
# → Должно быть >20 ГБ свободного места
```

#### Шаг 3.2: Развёртывание Harbor

Установка Harbor выполняется на выделенном узле (192.168.1.100) согласно **[инструкции по установке Harbor](../../../../Docker/Docker_registries/Harbor/installation.md)**.

**Последовательность действий:**
1. Выполните установку Harbor (рекомендуется версия v2.11+).
2. Создайте проект `k8s` и отметьте чекбокс **Public**.
3. Создайте проект `helm` (приватный по умолчанию).

**Проверка доступности Harbor:**
```bash
curl -sk https://harbor.domain.local/api/v2.0/health
# → {"status":"healthy"}

# Если Harbor использует самоподписанный сертификат — добавьте его на master-1:
sudo cp harbor-ca.crt /usr/local/share/ca-certificates/harbor-ca.crt
sudo update-ca-certificates
```

#### Шаг 3.3: Загрузка образов в локальный реестр

Процесс автоматизирует смену оригинальных тегов на локальные и загрузку в Harbor.

**Авторизация и импорт из архивов:**
```bash
export HARBOR="harbor.domain.local"
docker login $HARBOR
# → Login Succeeded

# Импорт всех tar-архивов в Docker-движок
cd /opt/kubespray-cache/images
for f in *.tar; do docker load -i "$f"; done
# → Loaded image: registry.k8s.io/kube-apiserver:v1.34.3
# → Loaded image: quay.io/cilium/cilium:v1.19.6
# → ... (ожидается >50 образов)
```

**Скрипт массового тегирования и Push:**
```bash
# Скрипт обрабатывает образы из популярных реестров и сохраняет иерархию путей
docker images --format '{{.Repository}}:{{.Tag}}' \
  | grep -E '^(quay\.io|registry\.k8s\.io|docker\.io|gcr\.io)/' \
  | while read img; do
      # Формирование целевого тега: harbor.domain.local/k8s/оригинальный_путь
      target="${HARBOR}/k8s/${img}"
      docker tag "$img" "$target"
      docker push "$target"
      # → Pushing harbor.domain.local/k8s/registry.k8s.io/kube-apiserver:v1.34.3...
    done
```

**Почему этот подход:**
- Скрипт автоматически определяет все образы из публичных реестров.
- Иерархия путей сохраняется: `harbor.domain.local/k8s/registry.k8s.io/...`.
- Тегирование выполняется «на лету» — не требуется ручное указание каждого образа.

**Валидация:**
```bash
# Проверка количества образов в Harbor (через API)
curl -sk https://$HARBOR/api/v2.0/projects/k8s/repositories \
  | python3 -m json.tool | grep name | wc -l
# → Ожидаемый результат: >30 репозиториев

# Проверка конкретного образа
curl -sk https://$HARBOR/v2/k8s/registry.k8s.io/kube-apiserver/tags/list
# → {"name":"k8s/registry.k8s.io/kube-apiserver","tags":["v1.34.3"]}
```

**Время выполнения:** Загрузка 50+ образов занимает 10-20 минут в зависимости от скорости сети между master-1 и harbor.

#### Шаг 3.4: Публикация Helm-чарта Cilium

Загрузка чарта в OCI-репозиторий Harbor для последующего использования в Kubespray.

```bash
# Авторизация в OCI-репозитории
helm registry login $HARBOR
# → Login Succeeded

# Публикация в проект helm
helm push /opt/kubespray-releases/cilium-1.19.6.tgz oci://$HARBOR/helm
# → Pushed: harbor.domain.local/helm/cilium:1.19.6
# → Digest: sha256:xxxx...
```

**Валидация:**
```bash
# Поиск чарта в OCI-репозитории
helm search oci://$HARBOR/helm/cilium --version 1.19.6
# → NAME                        CHART VERSION   APP VERSION
# → harbor.domain.local/helm/cilium   1.19.6          1.19.6
```

#### Шаг 3.5: Конфигурация Offline-инвентаря

Приведение переменных Ansible к реальности закрытого контура. После завершения этого шага Kubespray будет готов к развёртыванию кластера.

**1. Настройка `inventory.ini`:**

Обновите IP-адреса на фактические адреса узлов закрытой сети:

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

**2. Переменные реестра в `group_vars/all/offline.yml`:**

Укажите параметры реестра и registry mapping:

```yaml
---
# Параметры реестра
registry_host: "harbor.domain.local"
cilium_install_with_helm: true

# Публикация чарта Cilium через OCI
cilium_install_extra_flags: "--repository oci://{{registry_host}}/helm/cilium"

# Отключение digest (критично для offline — digest может измениться при docker save/load)
cilium_deploy_with_digest: false
hubble_ui_deploy_with_digest: false
cilium_operator_deploy_with_digest: false
```

> Подробный справочник переменных registry mapping доступен в **[Offline-концепциях: group_vars](./offline_concepts.md#12-переопределение-реестров-в-закрытом-конуре)**.

**Валидация:**
```bash
# Проверка подключения ко всем узлам
cd /opt/kuber_off/kubespray
ansible -i inventory/offline_cluster/inventory.ini all -m ping
# → master-1 | SUCCESS => { "changed": false, "ping": "pong" }
# → master-2 | SUCCESS => ...
# → node-1 | SUCCESS => ...
```

---

## Дополнительная информация

### Проверка готовности инфраструктуры

Перед запуском основного плейбука установки выполните финальные тесты:

```bash
#!/bin/bash
echo "--- ПРОВЕРКА ГОТОВНОСТИ ШАГА 3 ---"

# 1. Harbor доступен
if curl -sk https://harbor.domain.local/api/v2.0/health | grep -q '"healthy"'; then
    echo "[OK] Harbor доступен"
else
    echo "[FAIL] Harbor недоступен!"
fi

# 2. Проект k8s существует и Public
if curl -sk https://harbor.domain.local/api/v2.0/projects/k8s | grep -q '"public":true'; then
    echo "[OK] Проект k8s (Public)"
else
    echo "[FAIL] Проект k8s не найден или приватный!"
fi

# 3. Проект helm существует
if curl -sk https://harbor.domain.local/api/v2.0/projects/helm | grep -q '"name"'; then
    echo "[OK] Проект helm"
else
    echo "[FAIL] Проект helm не найден!"
fi

# 4. Критические образы в Harbor
for img in kube-apiserver kube-scheduler etcd coredns; do
    if curl -sk "https://harbor.domain.local/v2/k8s/registry.k8s.io/${img}/tags/list" | grep -q '"tags"'; then
        echo "[OK] $img в Harbor"
    else
        echo "[FAIL] $img отсутствует в Harbor!"
    fi
done

# 5. Helm-чарт Cilium
if helm search oci://harbor.domain.local/helm/cilium --version 1.19.6 2>/dev/null | grep -q "1.19.6"; then
    echo "[OK] Cilium chart в Harbor"
else
    echo "[FAIL] Cilium chart отсутствует!"
fi

# 6. Ansible connectivity
if ansible -i inventory/offline_cluster/inventory.ini all -m ping 2>/dev/null | grep -q "SUCCESS"; then
    echo "[OK] Ansible connectivity"
else
    echo "[FAIL] Ansible не может подключиться к узлам!"
fi

echo "--- ПРОВЕРКА ЗАВЕРШЕНА ---"
```

### Типовые ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `x509: certificate signed by unknown authority` | CA Harbor не установлен на узле | Скопируйте сертификат в `/usr/local/share/ca-certificates/` и `update-ca-certificates` |
| `project not found` | Проект `k8s` приватный | Установите `Public` в веб-интерфейсе Harbor |
| `manifest unknown` | Образ не загружен или неверный тег | Проверьте наличие в Harbor через API: `curl -sk https://harbor.domain.local/v2/k8s/.../tags/list` |
| `Connection refused` к Harbor | Harbor не запущен или файрвол блокирует | Проверьте статус Harbor: `docker ps` на harbor, проверьте файрвол |
| `denied: requested access to the resource is denied` | Токен авторизации истёк | Повторите `docker login` и `helm registry login` |
| Cilium pod `ImagePullBackOff` | Digest не совпадает (docker save/load изменил SHA) | Отключите digest: `cilium_deploy_with_digest: false` в offline.yml |

### Оптимизации

- **Очистка Docker-движка:** после завершения push удалите локальные образы, чтобы освободить место:
  ```bash
  docker image prune -a -f
  ```
- **Параллельная загрузка:** если между master-1 и harbor высокоскоростная сеть (>1 Гбит/с), можно запустить push в фоне:
  ```bash
  nohup bash -c 'docker images --format "{{.Repository}}:{{.Tag}}" | grep -E "^(quay|registry|docker|gcr)" | while read img; do docker tag "$img" "harbor.domain.local/k8s/$img" && docker push "harbor.domain.local/k8s/$img"; done' &
  ```
- **Повторный запуск:** если загрузка прервалась, повторный запуск скрипта тегирования пропустит уже загруженные образы (Harbor возвращает ошибку, скрипт продолжает).

### См. также

- **[Шаг 2: Подготовка окружения с интернетом](./step2_internet_env.md)** — откуда взялись архивы.
- **[Шаг 4: Развёртывание кластера](./step4_cluster_deploy.md)** — запуск финальной установки.
- **[Offline-концепции: registry mapping](./offline_concepts.md#12-переопределение-реестров-в-закрытом-конуре)** — справочник переменных перенаправления реестров.
