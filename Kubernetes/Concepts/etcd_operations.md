# Etcd: практические сценарии и операции

## Базовые операции с etcdctl

Для работы с etcd используется утилита `etcdctl`. Начиная с API v3, необходимо явно указать версию:

```bash
export ETCDCTL_API=3
```

### Запись и чтение данных

```bash
# Записать значение
etcdctl put foo bar
# OK

# Прочитать значение
etcdctl get foo
# foo
# bar

# Получить подробный вывод в JSON
etcdctl get --write-out=json foo
{
  "header": {
    "cluster_id": 14841639068965179712,
    "member_id": 10276657743932975437,
    "revision": 2,
    "raft_term": 2
  },
  "kvs": [{
    "key": "Zm9v",
    "create_revision": 2,
    "mod_revision": 2,
    "version": 1,
    "value": "YmFy"
  }],
  "count": 1
}
```

**Важно:** Ключи и значения возвращаются в кодировке base64, так как etcd хранит произвольные байтовые массивы, а не строки.

### Метаданные MVCC

* `version` — версия конкретного ключа (увеличивается при каждом изменении этого ключа)
* `create_revision` — глобальная ревизия, когда ключ был создан
* `mod_revision` — глобальная ревизия, когда ключ был изменён последний раз

**Глобальная ревизия (revision)** увеличивается при каждой операции записи в кластере. Это реализация [MVCC](../../etcd/mvcc_versioning_and_compaction.md).

### «Путешествие во времени» — чтение по ревизии

```bash
etcdctl put foo bar
etcdctl put foo baz

# Прочитать значение на ревизии 2
etcdctl get foo --rev=2 --print-value-only
# bar

# Прочитать значение на ревизии 3
etcdctl get foo --rev=3 --print-value-only
# baz
```

### Удаление ключей

```bash
etcdctl del foo
# 1 (количество удалённых ключей)

# Удаление не является постоянным до компакции — можно прочитать старую ревизию
etcdctl get foo --rev=3 --print-value-only
# baz
```

### Работа с диапазонами и префиксами

```bash
# Создать несколько ключей
etcdctl put myprefix/key1 thing1
etcdctl put myprefix/key2 thing2
etcdctl put myprefix/key3 thing3

# Получить диапазон ключей (включая начальный, исключая конечный)
etcdctl get myprefix/key2 myprefix/key4
# myprefix/key2
# thing2
# myprefix/key3
# thing3

# Получить все ключи с префиксом
etcdctl get --prefix myprefix/
# myprefix/key1
# thing1
# myprefix/key2
# thing2
# myprefix/key3
# thing3
```

---

## Наблюдение за изменениями (Watch)

Команда `watch` позволяет подписываться на изменения ключей в реальном времени — это основа работы контроллеров Kubernetes:

```bash
# В одном терминале — подписка на изменения
etcdctl watch --prefix myprefix/

# В другом терминале — изменения
etcdctl put myprefix/key1 anewthing
etcdctl put myprefix/key5 thing5
etcdctl del myprefix/key5

# Вывод в первом терминале:
# PUT
# myprefix/key1
# anewthing
# PUT
# myprefix/key5
# thing5
# DELETE
# myprefix/key5
```

### Watch с историей

Можно начать наблюдение с определённой ревизии, чтобы не пропустить события:

```bash
etcdctl watch --rev=2 foo
# PUT
# foo
# bar
# PUT
# foo
# baz
# DELETE
# foo
```

Это позволяет клиентам быть уверенными, что они не пропустят обновления после временного отключения.

---

## Типовые операции etcdctl

Для работы с `etcd` используется утилита `etcdctl`.

```bash
# Установить переменные для подключения
export ETCDCTL_API=3
EP="https://10.0.0.11:2379,https://10.0.0.12:2379,https://10.0.0.13:2379"
CA=/etc/etcd/ca.crt; CERT=/etc/etcd/client.crt; KEY=/etc/etcd/client.key

# Проверить статус кластера
etcdctl --endpoints=$EP --cacert=$CA --cert=$CERT --key=$KEY endpoint status -w=table

# Записать и прочитать значение
etcdctl --endpoints=$EP --cacert=$CA --cert=$CERT --key=$KEY put /k8s/demo "value"
etcdctl --endpoints=$EP --cacert=$CA --cert=$CERT --key=$KEY get /k8s/demo

# Создать снапшот
etcdctl --endpoints=$EP --cacert=$CA --cert=$CERT --key=$KEY snapshot save /backup/etcd.snap
```

---

## Интеграция с kube-apiserver

`kube-apiserver` настраивается для работы с `etcd` с помощью следующих флагов:

```bash
# Фрагмент аргументов kube-apiserver
--etcd-servers=https://10.0.0.11:2379,https://10.0.0.12:2379,https://10.0.0.13:2379
--etcd-cafile=/etc/kubernetes/pki/etcd/ca.crt
--etcd-certfile=/etc/kubernetes/pki/apiserver-etcd-client.crt
--etcd-keyfile=/etc/kubernetes/pki/apiserver-etcd-client.key
```

---

## Эксплуатационные рекомендации

| Аспект | Рекомендации |
| :--- | :--- |
| **Размер кластера** | 3–5 членов; избегать чётного числа; не масштабировать без необходимости. |
| **Диск** | Использовать быстрые SSD с низкой задержкой `fsync`; отключать swap. |
| **Сеть** | Защищать трафик с помощью TLS; задержка (RTT) между узлами <10 мс. |
| **Ресурсы** | Выделять отдельные CPU и ОЗУ; избегать конкуренции с другими рабочими нагрузками. |
| **Обслуживание** | Регулярно выполнять компакцию и дефрагментацию; настроить мониторинг и алертинг на размер БД. |
| **Совместимость** | Проверять совместимость версий `etcd` и Kubernetes перед обновлением. |
| **Бэкапы** | Настроить периодическое создание снапшотов и хранить их вне кластера; тестировать процедуру восстановления. |

---

## Связанные документы

* **[Etcd: основы](./etcd_basics.md)** — архитектура, свойства, роль в Kubernetes
* **[Кластеризация и восстановление](../../etcd/clustering_and_recovery.md)** — развёртывание и бэкап etcd
* **[Мониторинг etcd](../../etcd/etcd_monitoring.md)** — ключевые метрики и алертинг
