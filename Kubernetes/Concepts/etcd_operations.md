# etcd: практические сценарии и обслуживание в Kubernetes

## Определения

**etcdctl** — основной инструмент командной строки для управления данными и мониторинга состояния работающего кластера etcd (online-операции).

**etcdutl** — утилита для выполнения административных задач, требующих прямого доступа к файлам данных (offline-операции), таких как восстановление из снапшота или проверка состояния базы данных.

**Префикс `/registry`** — корневой путь в etcd, где Kubernetes хранит все свои объекты.

## Интеграция с Kubernetes

`kube-apiserver` является единственным компонентом, имеющим прямой доступ к etcd. Параметры TLS-аутентификации критически важны для безопасности кластера.

### Конфигурация kube-apiserver

Типовые флаги в манифесте `/etc/kubernetes/manifests/kube-apiserver.yaml`:

```bash
--etcd-servers=https://127.0.0.1:2379
--etcd-cafile=/etc/kubernetes/pki/etcd/ca.crt
--etcd-certfile=/etc/kubernetes/pki/apiserver-etcd-client.crt
--etcd-keyfile=/etc/kubernetes/pki/apiserver-etcd-client.key
```

### Доступ для администратора

Для выполнения команд на узле управления (Control Plane) необходимо использовать сертификаты самого etcd. Для удобства рекомендуется настроить alias:

```bash
export ETCDCTL_API=3
alias k-etcdctl="etcdctl --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key"
```

## Работа с данными Kubernetes

Все объекты Kubernetes (поды, секреты, конфигурации) сериализованы в формат **Protobuf**. Прямое чтение ключей через `etcdctl` вернет бинарные данные, непригодные для чтения человеком.

### Исследование структуры хранения

*   **Список всех типов ресурсов:**
    ```bash
    k-etcdctl get /registry --prefix --keys-only
    ```

*   **Поиск объектов по пути:**
    *   `/registry/pods/<namespace>/<name>` — данные о подах.
    *   `/registry/secrets/<namespace>/<name>` — секреты.
    *   `/registry/events/<namespace>/<name>` — события кластера (часто являются причиной роста БД).

## Обслуживание и мониторинг

### Проверка здоровья и статуса

*   **Здоровье всех эндпоинтов:**
    ```bash
    k-etcdctl endpoint health --cluster -w table
    ```

*   **Статус базы данных (размер, лидерство):**
    ```bash
    k-etcdctl endpoint status --cluster -w table
    ```

### Дефрагментация

Компакция (сжатие истории) выполняется автоматически API-сервером, но она лишь помечает место как свободное. Для физического уменьшения файла базы данных и возврата места ОС необходима дефрагментация.

> **Внимание:** Дефрагментация блокирует систему на запись. В кластере ее следует выполнять поочередно на каждом узле.

```bash
k-etcdctl defrag --cluster
```

### Управление аварийными сигналами (Alarms)

При достижении лимита памяти (обычно 2 ГБ или 8 ГБ) etcd переходит в режим `NOSPACE` и блокирует все записи.

1.  **Проверка наличия алармов:**
    ```bash
    k-etcdctl alarm list
    ```
2.  **Сброс всех алармов (после очистки/дефрагментации):**
    ```bash
    k-etcdctl alarm disarm
    ```

## Резервное копирование и восстановление

### Создание снапшота (Online)

Рекомендуется выполнять снапшот перед любыми критическими изменениями в кластере или обновлением версии Kubernetes. Поскольку etcd хранит все состояние кластера, наличие актуального снапшота гарантирует возможность восстановления в случае сбоя во время обновления.

```bash
ETCDCTL_API=3 etcdctl snapshot save /var/lib/kube-backups/etcd-snapshot-$(date +%F).db \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key
# → Snapshot saved at /var/lib/kube-backups/etcd-snapshot-2026-07-22.db
```

### Восстановление при аварии (Offline)

Процедура требует полной остановки компонентов Control Plane.

1.  **Остановка API-сервера:** Временно переместите `/etc/kubernetes/manifests/kube-apiserver.yaml` в другой каталог.
2.  **Восстановление данных через etcdutl:**
    ```bash
    etcdutl snapshot restore /var/lib/kube-backups/etcd-snapshot.db \
      --data-dir /var/lib/etcd-from-backup
    ```
3.  **Обновление конфигурации:** Укажите путь `/var/lib/etcd-from-backup` в манифесте `etcd.yaml`.
4.  **Запуск компонентов:** Верните манифесты в целевой каталог.

Детальная инструкция по восстановлению кворума: **[Кластеризация и восстановление etcd](../../etcd/clustering_and_recovery.md)**.

## Дополнительная информация

*   **[Шпаргалка по etcdctl](../../etcd/etcdctl_cheatsheet.md)** — полный список команд управления данными.
*   **[Обзор etcd в Kubernetes](./etcd_overview.md)** — концептуальное описание роли etcd и ее архитектуры.
*   **[Мониторинг etcd](../../etcd/etcd_monitoring.md)** — интеграция с Prometheus и ключевые метрики.
*   **[MVCC и компакция](../../etcd/mvcc_versioning_and_compaction.md)** — как работает версионирование данных.
