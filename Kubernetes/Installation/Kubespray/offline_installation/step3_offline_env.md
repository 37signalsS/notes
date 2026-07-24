# Kubespray: Offline установка — Шаг 3: Подготовка закрытого контура

## Определения

**Локальный реестр (Local Registry)** — сервер внутри изолированной сети (в данном руководстве — Harbor), предназначенный для хранения и раздачи контейнерных образов, Helm-чартов и OCI-артефактов без доступа к внешнему интернету.

**OCI-артефакты (OCI Artifacts)** — спецификация Open Container Initiative, позволяющая хранить в реестре не только образы, но и другие типы данных, такие как Helm-чарты.

---

## Основные концепции

### Цель этапа

Развёртывание и наполнение базовых сервисов внутри закрытого контура. Этот этап превращает загруженные на Шаге 2 артефакты в доступные для установщика ресурсы.

**Ключевые задачи:**

1. **Подготовка master-1:** настройка управляющего узла (Ansible Control Node) для работы в закрытом контуре.
2. **Развёртывание Harbor:** создание центрального хранилища образов и чартов.
3. **Миграция образов:** импорт, автоматизированное тегирование и загрузка образов Kubernetes в локальный реестр.
4. **Публикация Helm-чартов:** размещение чарта Cilium в OCI-репозитории Harbor.

### Требования к проектам в Harbor

Для корректной работы автоматизации Kubespray в Harbor должны быть созданы следующие логические разделы:

| Проект | Тип доступа | Назначение |
| :--- | :--- | :--- |
| **k8s** | **Публичный (Public)** | Все системные образы (k8s.gcr.io, quay.io, docker.io) |
| **helm** | Приватный (Private) | OCI-репозиторий для хранения Helm-чартов сетевого плагина |

> **Примечание:** Проект `k8s` должен быть публичным, чтобы `containerd` на узлах мог скачивать образы до момента настройки секретов аутентификации.

---

## Практические сценарии

### 1. Подготовка управляющего узла (master-1)

Выполните распаковку перенесенных архивов в системные директории.

```bash
# Распаковка исходного кода и бандла артефактов
tar -xzf ~/kubespray-code.tar.gz -C /opt/
tar -xzf ~/kubespray-offline-bundle.tar.gz -C /opt/
# → /opt/kuber_off/kubespray, /opt/kubespray-cache, /opt/kubespray-releases

# Установка бинарных файлов управления
sudo cp /opt/kubespray-releases/helm /usr/local/bin/
sudo chmod +x /usr/local/bin/helm
# → helm version: v3.16.x
```

### 2. Развёртывание Harbor

Установка Harbor выполняется на выделенном узле (192.168.1.100) согласно **[инструкции по установке Harbor](../../../../Docker/Docker_registries/Harbor/installation.md)**. 

**Последовательность действий:**
1. Выполните установку Harbor (рекомендуется версия v2.11+).
2. Создайте проект `k8s` и отметьте чекбокс **Public**.
3. Создайте проект `helm`.

### 3. Загрузка образов в локальный реестр

Процесс автоматизирует смену оригинальных тегов на локальные и загрузку в Harbor.

**Авторизация и импорт из архивов:**

```bash
export HARBOR="harbor.domain.local"
docker login $HARBOR
# → Login Succeeded

cd /opt/kubespray-cache/images
for f in *.tar; do docker load -i "$f"; done
# → Loaded image: registry.k8s.io/kube-apiserver:v1.34.3
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

### 4. Публикация Helm-чарта Cilium

Загрузка чарта в OCI-репозиторий Harbor для последующего использования в Kubespray.

```bash
helm registry login $HARBOR
# → Login Succeeded

# Публикация в проект helm
helm push /opt/kubespray-releases/cilium-1.19.6.tgz oci://$HARBOR/helm
# → Pushed: harbor.domain.local/helm/cilium:1.19.6
# → Digest: sha256:xxxx...
```

### 5. Конфигурация Offline-инвентаря

Приведение переменных Ansible к реальности закрытого контура.

**1. Настройка `inventory.ini`:**
Обновите IP-адреса на фактические адреса узлов закрытой сети.

**2. Переменные реестра:**
В файле `group_vars/all/offline.yml` (или аналогичном) укажите:
```yaml
registry_host: "harbor.domain.local"
files_repo: "http://harbor.domain.local:8080/v1/files" # Если используется файловый сервер
# Остальные параметры перенаправления описаны в основных концепциях
```

---

## Дополнительная информация

### Проверка готовности инфраструктуры

Перед запуском основного плейбука установки выполните финальные тесты:

1. **Проверка реестра:** зайдите в веб-интерфейс Harbor и убедитесь, что в проекте `k8s` появились репозитории (например, `k8s/registry.k8s.io/kube-apiserver`).
2. **Проверка связности Ansible:**

    ```bash
    cd /opt/kuber_off/kubespray
    ansible -i inventory/offline_cluster/inventory.ini all -m ping
    # → node-1 | SUCCESS => { "changed": false, "ping": "pong" }
    ```

### См. также

- **[Шаг 2: Подготовка окружения с интернетом](./step2_internet_env.md)** — откуда взялись архивы.
- **[Шаг 4: Развёртывание кластера](./step4_cluster_deploy.md)** — запуск финальной установки.
- **[Принципы offline-развертывания](./offline_concepts.md)** — подробный справочник всех переменных перенаправления.
