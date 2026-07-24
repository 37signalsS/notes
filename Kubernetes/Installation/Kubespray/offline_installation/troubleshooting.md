# Kubespray: Offline-установка — Устранение неполадок

## Определения

**Диагностика (Troubleshooting)** — процесс идентификации, анализа и устранения технических неисправностей, возникающих на различных этапах развёртывания и эксплуатации кластера в закрытом контуре.

**Конфликт Digest** — несовпадение контрольной суммы образа **SHA (Secure Hash Algorithm)** при его переносе между реестрами. Поскольку Kubespray по умолчанию проверяет целостность через digest, любые изменения при push в локальный Harbor могут блокировать запуск.

Общие определения ошибок Kubernetes приведены в **[глоссарии ошибок подов](../../../Troubleshooting/Common_Errors/PodImagePullErrors/definitions.md)**.

---

## Основные концепции

### Специфика диагностики в закрытом контуре

В изолированной среде отсутствие доступа к интернету превращает мелкие недочеты (например, забытый образ) в блокирующие ошибки.

**Ключевые зоны риска:**
- **Доверие TLS:** отсутствие корневого сертификата Harbor на узлах кластера.
- **Синхронизация времени:** рассинхрон NTP приводит к невалидности сертификатов K8s и Harbor.
- **Сетевая инкапсуляция:** проблемы с MTU при использовании VXLAN/Geneve поверх виртуальных сетей (VMware/Proxmox).
- **Python окружение:** отсутствие системных библиотек (например, `python3-apt`) внутри venv на pc-inet.

---

## Практические сценарии

### 1. Ошибки ImagePullBackOff (Реестр и Сертификаты)

Самая распространенная группа ошибок в offline-режиме.

**Симптом:** `kubectl describe pod` показывает `x509: certificate signed by unknown authority`.
**Решение:**
1. Убедитесь, что CA-сертификат Harbor добавлен на все узлы в `/usr/local/share/ca-certificates/`.
2. Выполните `sudo update-ca-certificates` и перезапустите containerd: `sudo systemctl restart containerd`.

**Симптом:** `Failed to pull image ... project not found`.
**Решение:** Убедитесь, что проект `k8s` в Harbor помечен как **Public**. Если проект приватный, необходимо настроить `containerd_registry_auth` в `group_vars/all/containerd.yml`.

### 2. Проблема Cilium: несовпадение SHA Digest

**Симптом:** Образ есть в Harbor, но Cilium-pod висит в `ImagePullBackOff`.
**Причина:** Kubespray прописывает жесткие digest для образов Cilium в ролях.
**Решение:** Отключите использование digest в `group_vars/all/offline.yml`:

```yaml
cilium_deploy_with_digest: false
# Также для Hubble и Operator
hubble_ui_deploy_with_digest: false
cilium_operator_deploy_with_digest: false
```

### 3. Проблемы связности: Cluster health unreachable

**Симптом:** Узлы видят друг друга по SSH, но поды не пингуются между узлами.
**Диагностика:** Проверьте MTU на интерфейсах: `ip link show`.
**Решение:** Для виртуальных сред (особенно VMware с MTU 1500) уменьшите MTU Cilium до 1450 в `group_vars/k8s_cluster/k8s-net-cilium.yml`:

```yaml
cilium_mtu: 1450
cilium_tunnel_mode: geneve # Geneve эффективнее VXLAN в vSphere
```

### 4. Ошибки Ansible: "python3-apt not found"

**Симптом:** Плейбук падает на этапе `gathering facts` или установки пакетов.
**Причина:** Ansible внутри venv не видит системный модуль `apt`.
**Решение:** Установите `python3-apt` в системе и создайте venv с доступом к системным пакетам:
```bash
python3 -m venv --system-site-packages venv
```

### 5. Рассинхронизация времени (NTP)

**Симптом:** Непонятные ошибки `Unauthorized` или `Expired certificate`.
**Решение:** Установите и настройте `chrony` или `ntp` на всех узлах, направив их на локальный источник точного времени.

---

## Дополнительная информация

### Команды быстрой диагностики на узле

**Проверка работы containerd:**
```bash
sudo crictl ps        # Список запущенных контейнеров
sudo crictl images    # Список загруженных образов
```

**Проверка логов системных сервисов:**
```bash
sudo journalctl -u kubelet -f --no-pager
sudo journalctl -u containerd -f --no-pager
```

**Анализ сетевых сбросов (Drop) через Cilium:**
```bash
kubectl -n kube-system exec ds/cilium -- hubble observe --type drop
```

### См. также

- **[Проверка кластера](./cluster_verification.md)** — регламент валидации систем.
- **[План offline-установки](./offline_practical.md)** — дорожная карта проекта.
- **[Общая диагностика Air-gapped](../../../Troubleshooting/Common_Errors/PodImagePullErrors/airgapped.md)**.
