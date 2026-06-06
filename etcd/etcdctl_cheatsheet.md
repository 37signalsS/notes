# etcdctl: шпаргалка по командам

## Определения

**etcdctl** — утилита командной строки для взаимодействия с сервером **etcd**.

**ETCDCTL_API=3** — переменная окружения, активирующая поддержку API версии 3 (стандарт для современных версий).

## Основные концепции

Для работы с защищённым кластером необходимо указывать сертификаты и точки подключения (endpoints).

```bash
export ETCDCTL_API=3
export ENDPOINTS="https://127.0.0.1:2379"
export CA="/etc/etcd/ca.crt"
export CERT="/etc/etcd/server.crt"
export KEY="/etc/etcd/server.key"

# Базовая команда
etcdctl --endpoints=$ENDPOINTS --cacert=$CA --cert=$CERT --key=$KEY <command>
```

## Практические сценарии

### Управление данными

* **Запись и чтение:**
  ```bash
  etcdctl put mykey "myvalue"
  etcdctl get mykey
  ```
* **Чтение по префиксу:**
  ```bash
  etcdctl get /configs --prefix
  ```
* **Удаление:**
  ```bash
  etcdctl del mykey
  etcdctl del /configs --prefix
  ```

### Состояние кластера

* **Проверка здоровья:**
  ```bash
  etcdctl endpoint health --cluster -w table
  ```
* **Статус и использование ресурсов:**
  ```bash
  etcdctl endpoint status --cluster -w table
  ```
* **Список участников кластера:**
  ```bash
  etcdctl member list -w table
  ```

### Резервное копирование

* **Создание снапшота:**
  ```bash
  etcdctl snapshot save backup.db
  ```
* **Проверка снапшота:**
  ```bash
  etcdctl snapshot status backup.db
  ```
* **Восстановление (используется etcdutl в 3.6+):**
  ```bash
  etcdutl snapshot restore backup.db --data-dir /var/lib/etcd-new
  ```

## Дополнительная информация

* **[Архитектура и основные концепции](./architecture-and-concepts.md)** — Lease, Watch, Revision.
* **[Кластеризация и восстановление](./clustering_and_recovery.md)** — детальное руководство по аварийным ситуациям.
* **[MVCC и версионирование](./mvcc_versioning_and_compaction.md)** — работа с историей изменений.
