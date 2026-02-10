# Автоматическое восстановление и кластеризация etcd

Кластер etcd строится поверх консенсуса Raft: в каждый момент времени есть лидер, принимающий запись, и фолловеры, реплицирующие лог. Автоматическое восстановление достигается за счет повторного выбора лидера при сбоях, журналирования (WAL) и механизма снапшотов, позволяющих узлам догонять кластер после перезапуска.

## Топология и кворум

-   Рекомендуется нечетное число участников.
-   Кворум = floor(N/2) + 1; число допустимых одновременных отказов = N − кворум.

| N узлов | Кворум | Допустимо отказов |
|---|---|---|
| 1 | 1 | 0 |
| 3 | 2 | 1 |
| 5 | 3 | 2 |

Сетевые задержки и разрывы могут имитировать отказ; критично обеспечивать стабильную сеть для peer-трафика.

## Базовая конфигурация кластера

Ключевые параметры запуска:

-   `--name`: уникальное имя участника.
-   `--data-dir`: постоянное хранилище данных.
-   `--listen-client-urls` / `--advertise-client-urls`: для клиентов.
-   `--listen-peer-urls` / `--initial-advertise-peer-urls`: для межузловой репликации.
-   `--initial-cluster`: список участников с peer-URL.
-   `--initial-cluster-state`: `new` для нового кластера, `existing` при присоединении/перезапуске.
-   TLS: `--cert-file`/`--key-file`/`--trusted-ca-file` для клиентского, `--peer-cert-file`/`--peer-key-file`/`--peer-trusted-ca-file` для межузлового шифрования.

Пример systemd-юнита с TLS и статической кластеризацией:

```ini
[Unit]
Description=etcd
After=network.target

[Service]
Type=notify
User=etcd
ExecStart=/usr/local/bin/etcd 
  --name=node1 
  --data-dir=/var/lib/etcd 
  --listen-client-urls=https://0.0.0.0:2379 
  --advertise-client-urls=https://node1:2379 
  --listen-peer-urls=https://0.0.0.0:2380 
  --initial-advertise-peer-urls=https://node1:2380 
  --initial-cluster=node1=https://node1:2380,node2=https://node2:2380,node3=https://node3:2380 
  --initial-cluster-state=new 
  --cert-file=/etc/etcd/tls/server.crt 
  --key-file=/etc/etcd/tls/server.key 
  --trusted-ca-file=/etc/etcd/tls/ca.crt 
  --peer-cert-file=/etc/etcd/tls/peer.crt 
  --peer-key-file=/etc/etcd/tls/peer.key 
  --peer-trusted-ca-file=/etc/etcd/tls/ca.crt 
  --auto-compaction-retention=1h
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

## Автоматическое восстановление узлов

При перезапуске участник реплейт WAL, применяет локальный снапшот и догоняет лидера через потоковые снапшоты и лог. Для сохранения работоспособности:

-   Хранить data-dir на надежном диске и не очищать без необходимости.
-   Обеспечить совпадение name и advertise-URL с параметрами, известными кластеру.
-   Следить за временем выборов: `--election-timeout` и `--heartbeat-interval` должны соответствовать сетевым условиям.

Служебные операции:

```bash
etcdctl --endpoints=https://node1:2379,https://node2:2379,https://node3:2379 endpoint health --cluster
etcdctl snapshot save /backups/etcd-$(date +%F).db
etcdctl snapshot restore /backups/etcd.db --data-dir=/var/lib/etcd-restore
```

## Замена вышедшего из строя участника

1) Удалить недоступный член:

```sql
etcdctl member list
etcdctl member remove <memberID>
```

2) Добавить новый с его peer-URL:

```sql
etcdctl member add node3 --peer-urls=https://node3:2380
```

Команда вернет строку для `--initial-cluster`; запустить новый узел с пустым data-dir и `--initial-cluster-state=existing`, используя выданные значения.

## Профилактика деградации

-   Автокомпакция для снижения объема исторических ревизий:
    ```ini
    --auto-compaction-retention=12h
    ```
-   Регулярная дефрагментация для reclaim диска:
    ```css
    etcdctl defrag --cluster
    ```
-   Контроль квоты хранилища:
    ```ini
    --quota-backend-bytes=8G
    ```
-   Реакция на тревоги:
    ```perl
    etcdctl alarm list
    etcdctl alarm disarm
    ```

## Наблюдение за здоровьем

-   Проверка линз сервисов:
    ```lua
    etcdctl endpoint status --cluster --write-out=table
    ```
-   Метрики и логи лидера и фолловеров позволяют оценивать задержки репликации, количество выборов и объем WAL; рост этих показателей указывает на сетевые или дисковые проблемы.
