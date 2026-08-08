# etcd: практические сценарии и обслуживание в Kubernetes

## Определение

В контексте Kubernetes **обслуживание etcd** — это комплекс регулярных и аварийных процедур, направленных на поддержание стабильности, производительности и целостности базы данных кластера.

Для управления etcd используются две основные утилиты:
*   **`etcdctl`**: Основной клиент (gRPC) для работы с запущенным кластером (online-операции: чтение данных, проверка здоровья, дефрагментация, создание снапшотов).
*   **`etcdutl`**: Утилита (начиная с v3.6+) для административных задач, требующих прямого доступа к физическим файлам базы данных (offline-операции: восстановление из снапшота, проверка целостности файла).

**Префикс `/registry`** — корневой путь в etcd, по которому Kubernetes хранит все свои сериализованные объекты.

---

## Интеграция с Kubernetes и доступ

`kube-apiserver` является единственным компонентом Kubernetes, имеющим прямой доступ к etcd. 

### Конфигурация доступа

Параметры TLS-аутентификации задаются во флагах `kube-apiserver` (обычно в `/etc/kubernetes/manifests/kube-apiserver.yaml`):

```bash
--etcd-servers=https://127.0.0.1:2379
--etcd-cafile=/etc/kubernetes/pki/etcd/ca.crt
--etcd-certfile=/etc/kubernetes/pki/apiserver-etcd-client.crt
--etcd-keyfile=/etc/kubernetes/pki/apiserver-etcd-client.key
```

### Настройка CLI для администратора

Для выполнения команд `etcdctl` на узле Control Plane необходимо использовать клиентские сертификаты. Для удобства рекомендуется настроить alias в профиле пользователя:

```bash
export ETCDCTL_API=3
alias k-etcdctl="etcdctl --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/healthcheck-client.crt \
  --key=/etc/kubernetes/pki/etcd/healthcheck-client.key"
```
*(В kubeadm-кластерах удобнее использовать `healthcheck-client` или `server` сертификаты, лежащие в `/etc/kubernetes/pki/etcd/`)*.

---

## Работа с данными Kubernetes

Все объекты Kubernetes сериализуются и хранятся в формате **Protobuf** (начиная с K8s 1.6+). Прямое чтение ключей через `etcdctl` вернет бинарные данные, которые сложно прочитать человеку, однако это полезно для отладки структуры.

### Исследование структуры хранения

*   **Список всех доступных префиксов (типов ресурсов):**
    ```bash
    k-etcdctl get /registry --prefix --keys-only
    ```

*   **Типовые пути K8s:**
    *   `/registry/pods/<namespace>/<name>`
    *   `/registry/secrets/<namespace>/<name>`
    *   `/registry/events/<namespace>/<name>` — частая причина разрастания БД в нестабильных кластерах.
    *   `/registry/leases/kube-node-lease/<node-name>` — Heartbeats узлов.

---

## Обслуживание и мониторинг

### Проверка здоровья и статуса

Перед любыми операциями всегда проверяйте кворум:

```bash
# Проверка доступности узлов
k-etcdctl endpoint health --cluster -w table

# Проверка размера БД, ревизии и кто является лидером
k-etcdctl endpoint status --cluster -w table
```

### Компакция и Дефрагментация

В Kubernetes API-сервер автоматически выполняет **компакцию** (сжатие истории версий MVCC) каждые 5 минут. Однако компакция лишь помечает место в БД как свободное, не возвращая его файловой системе.

Для физического уменьшения файла базы данных необходима **дефрагментация**.

> **ВНИМАНИЕ:** Дефрагментация блокирует узел на чтение и запись до завершения процесса. В HA-кластере ее необходимо выполнять **строго поочередно** на каждом узле, а не через флаг `--cluster`, чтобы не потерять кворум.

```bash
# Правильный подход: дефрагментация конкретного узла
k-etcdctl --endpoints=https://10.0.0.11:2379 defrag
k-etcdctl --endpoints=https://10.0.0.12:2379 defrag
```

### Устранение ошибки "database space exceeded" (NOSPACE)

По умолчанию etcd имеет жесткий лимит на размер базы данных (обычно 2GB). Если БД достигает этого предела (часто из-за шторма событий K8s или отсутствия дефрагментации), etcd переходит в режим "только чтение" и генерирует Alarm `NOSPACE`. K8s API-сервер перестает принимать изменения.

**Алгоритм восстановления:**
1.  **Получите текущую ревизию:**
    ```bash
    rev=$(k-etcdctl endpoint status --write-out="json" | egrep -o '"revision":[0-9]*' | egrep -o '[0-9]*' | head -n 1)
    ```
2.  **Выполните ручную компакцию:**
    ```bash
    k-etcdctl compaction $rev
    ```
3.  **Выполните дефрагментацию на всех узлах:**
    ```bash
    k-etcdctl defrag --cluster
    ```
4.  **Снимите блокировку (Disarm Alarm):**
    ```bash
    k-etcdctl alarm list
    k-etcdctl alarm disarm
    ```

---

## Резервное копирование и восстановление

### Создание снапшота (Online Backup)

Снапшот etcd — единственный надежный способ забекапить весь кластер K8s целиком. Выполняйте его перед мажорными обновлениями кластера.

```bash
# Создание бекапа
k-etcdctl snapshot save /var/lib/kube-backups/etcd-snapshot-$(date +%F).db

# Проверка целостности созданного файла (используется etcdutl)
etcdutl snapshot status /var/lib/kube-backups/etcd-snapshot-$(date +%F).db -w table
```

### Восстановление при аварии (Offline Restore)

Восстановление выполняется, когда кластер полностью разрушен или потерян кворум. Операция требует остановки Control Plane.

1.  **Остановите API-сервер и etcd** (например, убрав манифесты из `/etc/kubernetes/manifests/`).
2.  **Восстановите данные из файла в новую директорию:**
    ```bash
    # Для etcd 3.6+ обязательно использование etcdutl
    etcdutl snapshot restore /var/lib/kube-backups/etcd-snapshot.db \
      --data-dir /var/lib/etcd-from-backup
    ```
3.  **Обновите конфигурацию etcd:** Укажите новый `data-dir` (`/var/lib/etcd-from-backup`) в манифесте `etcd.yaml`.
4.  **Запустите компоненты:** Верните манифесты в `/etc/kubernetes/manifests/`.

*Детальное руководство по восстановлению многоузлового кворума:* **[Кластеризация и восстановление etcd](../../etcd/clustering_and_recovery.md)**.

---

## Продвинутая диагностика: "Request entity too large"

Если Kubernetes возвращает ошибку `etcdserver: request is too large`, это означает, что размер объекта (например, ConfigMap или Secret) превышает `max-request-bytes` (по умолчанию 1.5 MB).

*   **Решение 1:** Разбить ConfigMap на несколько частей.
*   **Решение 2:** Если разбиение невозможно, увеличьте лимит, добавив флаг `--max-request-bytes=3145728` в манифест `etcd.yaml` (и перезапустите etcd).

---

## Дополнительная информация

**Связанные ресурсы:**
*   **[Шпаргалка по командам etcdctl](../../etcd/etcdctl_cheatsheet.md)** — подробный справочник команд.
*   **[Обзор etcd в Kubernetes](./etcd_overview.md)** — архитектурная роль компонента.
*   **[MVCC, версионирование и компакция](../../etcd/mvcc_versioning_and_compaction.md)** — глубокое понимание устройства хранения etcd.
*   **[Резервное копирование в Kubernetes](../Operations/backup-strategies.md)** — сравнение бэкапа etcd с инструментами типа Velero.
