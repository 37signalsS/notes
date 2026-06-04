# Etcd: практические сценарии для Kubernetes

## Определения

**etcdctl** — утилита командной строки для взаимодействия с etcd. Для Kubernetes используется API v3.

**ETCDCTL_API=3** — переменная окружения, указывающая на использование API версии 3 (требуется для всех современных версий etcd).

## Основные концепции

### Подключение к etcd в Kubernetes

Для прямого подключения к etcd требуются сертификаты клиента. Параметры подключения:

```bash
export ETCDCTL_API=3
EP="https://10.0.0.11:2379,https://10.0.0.12:2379,https://10.0.0.13:2379"
CA=/etc/kubernetes/pki/etcd/ca.crt
CERT=/etc/kubernetes/pki/etcd/healthcheck-client.crt
KEY=/etc/kubernetes/pki/etcd/healthcheck-client.key
```

### Интеграция с kube-apiserver

`kube-apiserver` подключается к `etcd` через следующие флаги:

```bash
--etcd-servers=https://10.0.0.11:2379,https://10.0.0.12:2379,https://10.0.0.13:2379
--etcd-cafile=/etc/kubernetes/pki/etcd/ca.crt
--etcd-certfile=/etc/kubernetes/pki/apiserver-etcd-client.crt
--etcd-keyfile=/etc/kubernetes/pki/apiserver-etcd-client.key
```

Эти параметры настраиваются при инициализации кластера (kubeadm, kubespray) и не должны изменяться вручную.

## Практические сценарии

### Проверка состояния кластера

```bash
etcdctl --endpoints=$EP --cacert=$CA --cert=$CERT --key=$KEY endpoint health
# https://10.0.0.11:2379: healthy

# Статус конкретных эндпоинтов
etcdctl --endpoints=$EP --cacert=$CA --cert=$CERT --key=$KEY endpoint status -w=table

# Состояние всего кластера
etcdctl --endpoints=$EP --cacert=$CA --cert=$CERT --key=$KEY \
  endpoint status --cluster -w=table
```

### Просмотр данных Kubernetes в etcd

**Префикс `/registry`:** Все объекты Kubernetes хранятся с этим префиксом.

```bash
# Просмотр всех подов в namespace default
etcdctl --endpoints=$EP --cacert=$CA --cert=$CERT --key=$KEY \
  get /registry/pods/default --prefix --keys-only

# Просмотр конкретного Secret
etcdctl --endpoints=$EP --cacert=$CA --cert=$CERT --key=$KEY \
  get /registry/secrets/default/my-secret
```

> **Важно:** Данные в etcd хранятся в бинарном формате (Protobuf). Прямое чтение показывает нечитаемые данные. Используйте `kubectl get` для просмотра в JSON/YAML.

### Создание снапшота для резервного копирования

```bash
etcdctl --endpoints=$EP --cacert=$CA --cert=$CERT --key=$KEY \
  snapshot save /backup/etcd-$(date +%F).db
```

> **Важно (etcd 3.6+):** Команда `snapshot restore` перемещена в утилиту `etcdutl`. Используйте `etcdutl snapshot restore` для восстановления.

Подробнее о восстановлении: [Кластеризация и восстановление etcd](../../etcd/clustering_and_recovery.md).

### Чтение по ревизии (MVCC)

Etcd поддерживает чтение данных на момент времени через ревизии:

```bash
# Получить значение на конкретной ревизии
etcdctl --endpoints=$EP --cacert=$CA --cert=$CERT --key=$KEY \
  get /registry/configmaps/default/app-config --rev=12345
```

Полезно для отката изменений или аудита. Подробнее: [MVCC и версионирование](../../etcd/mvcc_versioning_and_compaction.md).

### Наблюдение за изменениями (Watch)

Контроллеры Kubernetes используют `watch` для отслеживания изменений:

```bash
# Подписка на изменения подов в реальном времени
etcdctl --endpoints=$EP --cacert=$CA --cert=$CERT --key=$KEY \
  watch --prefix /registry/pods/
```

При создании/удалении пода в терминал будут поступать события.

## Дополнительная информация

**Эксплуатационные рекомендации:**

* **Размер кластера:** 3–5 членов, избегать чётного числа
* **Диск:** Быстрые SSD с низкой задержкой `fsync`, отключить swap
* **Сеть:** TLS обязателен, задержка между узлами <10 мс
* **Обслуживание:** Регулярная компакция и дефрагментация
* **Бэкапы:** Периодические снапшоты вне кластера, тестирование восстановления
