# etcd: практические сценарии в Kubernetes

## Определения

**etcdctl** — утилита командной строки для взаимодействия с **etcd**. В Kubernetes используется исключительно **API (Application Programming Interface)** версии 3.

**Префикс `/registry`** — корневой путь в etcd, где Kubernetes хранит все свои объекты (Pods, Services, Secrets).

## Основные концепции

### Интеграция с kube-apiserver

`kube-apiserver` является единственным клиентом etcd в кластере. Параметры подключения задаются флагами при запуске (в манифестах статических подов `/etc/kubernetes/manifests/kube-apiserver.yaml`). Безопасность обеспечивается через **TLS (Transport Layer Security)**:

```bash
--etcd-servers=https://127.0.0.1:2379
--etcd-cafile=/etc/kubernetes/pki/etcd/ca.crt
--etcd-certfile=/etc/kubernetes/pki/apiserver-etcd-client.crt
--etcd-keyfile=/etc/kubernetes/pki/apiserver-etcd-client.key
```

### Доступ для администратора

Для выполнения команд `etcdctl` на узле с Control Plane необходимо использовать сертификаты из каталога `/etc/kubernetes/pki/etcd/`.

```bash
export ETCDCTL_API=3
alias k-etcdctl="etcdctl --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key"
```

## Практические сценарии

### Просмотр ресурсов Kubernetes

Все данные сериализуются в формат **Protobuf**, поэтому прямое чтение ключей через `etcdctl` вернёт бинарные данные. Для анализа объектов рекомендуется использовать `kubectl`.

* **Список всех ключей (структура хранения):**
  ```bash
  k-etcdctl get /registry --prefix --keys-only
  ```
* **Поиск подов в конкретном пространстве имён (namespace):**
  ```bash
  k-etcdctl get /registry/pods/default --prefix --keys-only
  ```

### Создание резервной копии (Snapshot)

Снапшот необходимо выполнять на одном из узлов etcd.

```bash
k-etcdctl snapshot save /var/lib/kube-backups/etcd-snapshot-$(date +%F).db
```

### Восстановление при аварии

> **Важно:** Восстановление требует остановки `kube-apiserver` и использования утилиты `etcdutl`.

1. Остановить API Server (переместить манифест из `/etc/kubernetes/manifests/`).
2. Выполнить восстановление в новый каталог данных.
3. Обновить путь к данным в манифесте etcd.
4. Вернуть манифесты на место.

Детальная процедура: **[Кластеризация и восстановление etcd](../../etcd/clustering_and_recovery.md)**.

## Дополнительная информация

*   **[Шпаргалка по командам etcdctl](../../etcd/etcdctl_cheatsheet.md)** — общие операции с данными и кластером.
*   **[Обзор etcd в Kubernetes](./etcd_overview.md)** — роль в архитектуре и требования к инфраструктуре.
*   **[Мониторинг etcd](../../etcd/etcd_monitoring.md)** — ключевые метрики и алертинг.
