# Тип Service — ExternalName

## Определения

**ExternalName** — специальный тип Service в Kubernetes, который выполняет роль DNS-псевдонима. Вместо проксирования трафика через сетевой стек кластера (kube-proxy) или использования виртуальных IP (ClusterIP), он возвращает клиенту CNAME-запись, указывающую на внешнее доменное имя.

**Ключевое отличие:** Это единственный тип сервиса, который не имеет ClusterIP, не использует селекторы подов и не создает объекты Endpoints или EndpointSlices.

## Предварительные требования

Для работы с ExternalName Service необходимо обеспечить следующее окружение:

- **Кластер Kubernetes** версии 1.21+ (для стабильной поддержки CoreDNS)
- **CoreDNS** — кластерный DNS-сервер для создания CNAME-записей
- **kubectl** — CLI-инструмент для управления ресурсами кластера
- **Доступ к внешнему ресурсу** — доменное имя, указанное в `externalName`, должно быть разрешимо из подов

**Проверка готовности окружения:**
```bash
# Проверка CoreDNS
kubectl -n kube-system get pods -l k8s-app=kube-dns
# → Все поды должны быть в статусе Running и Ready

# Проверка работы DNS из тестового пода
kubectl run dns-test --rm -it --image=busybox:1.37 -- nslookup kubernetes.default.svc.cluster.local
# → Должен вернуть IP-адрес сервиса kubernetes

# Проверка разрешения внешнего имени (замените на ваш externalName)
kubectl run dns-test --rm -it --image=busybox:1.37 -- nslookup rds-instance-01.cxyz.eu-central-1.rds.amazonaws.com
# → Должен вернуть IP-адрес внешнего ресурса
```

## Основные концепции

### Механика работы

При обращении клиента к сервису типа ExternalName (например, `my-service.prod.svc.cluster.local`), внутренний DNS-сервер (CoreDNS) возвращает ответ типа CNAME с адресом, указанным в поле `externalName`.

**Процесс разрешения:**
1. Приложение запрашивает DNS-имя сервиса.
2. CoreDNS находит запись `ExternalName` в своей базе.
3. CoreDNS возвращает CNAME, указывающий на внешний ресурс (например, `db.external.com`).
4. Резолвер клиентского пода выполняет второй (рекурсивный) запрос для разрешения `db.external.com` в IP-адрес.
5. Клиент устанавливает прямое соединение с полученным внешним IP.

### Роль портов

Хотя поле `spec.ports` является необязательным для `ExternalName`, его использование имеет важное значение:
- **Игнорирование ядром:** Kubernetes не выполняет проброс портов для этого типа сервиса. Если клиент обращается на порт `8080`, запрос пойдет на порт `8080` внешнего хоста, независимо от того, что указано в манифесте.
- **Документирование:** Указание портов служит "живой документацией" для инженеров.
- **Интеграция с Service Mesh:** Прокси-серверы (Envoy в Istio/Linkerd) используют список портов для корректной маршрутизации и применения политик трафика.

### Взаимодействие с Service Mesh (Istio / Linkerd)

Использование `ExternalName` внутри меша требует осторожности:
- **mTLS:** Меш может попытаться применить взаимный TLS к внешнему ресурсу, который его не поддерживает. Для `ExternalName` обычно требуется явно отключить mTLS (например, через `DestinationRule` в Istio).
- **DNS Proxying:** Включение DNS-проксирования в меше позволяет перехватывать запросы к `ExternalName` на уровне sidecar, что ускоряет резолвинг и позволяет использовать Egress Gateway.

### Характеристики и особенности

- **Минимальные накладные расходы:** Трафик идет напрямую от пода к внешнему ресурсу, не нагружая `kube-proxy` и не проходя через цепочки NAT (iptables/nftables).
- **Работа на уровне DNS:** Весь механизм реализован исключительно через конфигурацию CoreDNS.
- **Протокольная независимость:** Работает для TCP, UDP и любых L7-протоколов (HTTP, gRPC, базы данных).
- **Динамическое управление:** Позволяет менять адрес внешней зависимости (например, при переезде на другой инстанс БД) без перезапуска приложений.

## Практические сценарии

### Пример манифеста

```yaml
apiVersion: v1
kind: Service
metadata:
  name: cloud-db
  namespace: development
spec:
  type: ExternalName
  externalName: rds-instance-01.cxyz.eu-central-1.rds.amazonaws.com
  ports:
  - name: postgres
    port: 5432
    protocol: TCP
```

**Валидация созданного сервиса:**
```bash
# Проверка создания сервиса (ClusterIP должен отсутствовать)
kubectl get svc cloud-db -n development
# → NAME      TYPE         EXTERNAL-IP   PORT(S)    AGE
# → cloud-db  ExternalName   <none>        5432/TCP   5s

# Проверка DNS-записи из тестового пода
kubectl run dns-test --rm -it --image=busybox:1.37 -n development -- nslookup cloud-db.development.svc.cluster.local
# → Server:    10.96.0.10
# → Address:   10.96.0.10#53
# →
# → cloud-db.development.svc.cluster.local canonical name = rds-instance-01.cxyz.eu-central-1.rds.amazonaws.com.

# Проверка сетевой связности до внешнего ресурса
kubectl run connectivity-test --rm -it --image=busybox:1.37 -n development -- nc -zv rds-instance-01.cxyz.eu-central-1.rds.amazonaws.com 5432
# → Connection to rds-instance-01.cxyz.eu-central-1.rds.amazonaws.com 5432 port [tcp/postgresql] succeeded!

# Проверка что трафик идет напрямую (без проксирования)
kubectl run tcpdump --rm -it --image=nicolaka/netshoot -n development -- tcpdump -i eth0 host <external-ip> -c 5
```

### Тонкости работы с HTTP и SSL/TLS

Использование `ExternalName` для HTTP-сервисов (HTTPS API, внешние веб-сервисы) часто приводит к ошибкам из-за несоответствия имен:

1. **Заголовок Host:** При обращении к `http://cloud-db/` клиент отправляет заголовок `Host: cloud-db`. Внешний сервер (например, Nginx или Cloudflare) может отклонить запрос, так как ожидает заголовок с его реальным именем.
2. **SSL/TLS и SNI:** При установке защищенного соединения клиент отправляет имя сервиса (`cloud-db`) в поле SNI. Если внешний сервер использует сертификат только для своего реального имени, проверка SSL завершится ошибкой `Hostname mismatch`.

**Решение:** Для HTTP-зависимостей может потребоваться промежуточный прокси (Ingress или Sidecar), который будет подменять заголовок `Host` и переписывать SNI (TLS Origination).

### Типовые сценарии использования

- **Managed-базы данных:** Обращение к RDS, Cloud SQL или Redis по коротким стабильным именам.
- **Внешние API:** Абстрагирование URL сторонних шлюзов (платежные системы, SMS-сервисы).
- **Миграция "Legacy -> K8s":** Постепенный перенос компонентов из старой инфраструктуры в кластер с сохранением имен.
- **Косвенная балансировка нагрузки:** Указание на DNS-имя внешнего балансировщика нагрузки для использования механизмов отказоустойчивости провайдера.
- **Разделение сред:** `db-service` в namespace `dev` указывает на локальный контейнер БД, а в `prod` — на `ExternalName`, ведущий в облако.

## Устранение неполадок (Troubleshooting)

### Проблема 1: DNS не разрешает имя сервиса

**Симптом:** Приложение внутри кластера не может обратиться к ExternalName-сервису по имени.

**Диагностика:**
```bash
# Проверка существования сервиса
kubectl get svc cloud-db -n development
# → Сервис должен существовать с типом ExternalName

# Проверка CoreDNS
kubectl -n kube-system get pods -l k8s-app=kube-dns
# → Все поды должны быть Running

# Проверка DNS из тестового пода
kubectl run dns-test --rm -it --image=busybox:1.37 -n development -- nslookup cloud-db.development.svc.cluster.local
# → Ожидаемый результат: CNAME-запись на внешний ресурс
```

**Типичные причины и решения:**

| Причина | Диагностика | Решение |
| :--- | :--- | :--- |
| CoreDNS не запущен | `kubectl -n kube-system get pods` — поды не Running | Проверить логи CoreDNS, перезапустить поды |
| Неправильное имя сервиса | Опечатка в FQDN | Проверить имя сервиса и namespace |
| NetworkPolicy блокирует DNS | `kubectl get networkpolicy -A` | Разрешить трафик на порт 53 (UDP/TCP) к CoreDNS |
| Сервис в другом namespace | `kubectl get svc -A grep cloud-db` | Использовать полное FQDN с правильным namespace |

### Проблема 2: Внешний ресурс недоступен

**Симптом:** DNS разрешает имя, но соединение с внешним ресурсом не устанавливается.

**Диагностика:**
```bash
# Проверка разрешения внешнего имени напрямую
kubectl run dns-test --rm -it --image=busybox:1.37 -- nslookup rds-instance-01.cxyz.eu-central-1.rds.amazonaws.com
# → Должен вернуть IP-адрес

# Проверка сетевой связности
kubectl run connectivity-test --rm -it --image=busybox:1.37 -- nc -zv rds-instance-01.cxyz.eu-central-1.rds.amazonaws.com 5432
# → Ожидаемый результат: Connection succeeded

# Проверка маршрутизации (для on-premise)
kubectl run traceroute --rm -it --image=busybox:1.37 -- traceroute rds-instance-01.cxyz.eu-central-1.rds.amazonaws.com
```

**Типичные причины:**
- Файрвол блокирует исходящий трафик из кластера
- Внешний ресурс недоступен (проверить статус у провайдера)
- Неправильный порт в настройках приложения
- DNS-имя внешнего ресурса изменилось

### Проблема 3: SSL/TLS ошибки при работе с HTTP

**Симптом:** Приложение получает ошибки сертификата при обращении к внешнему HTTPS-сервису через ExternalName.

**Диагностика:**
```bash
# Проверка SSL-сертификата внешнего ресурса
kubectl run ssl-test --rm -it --image=alpine/openssl -- s_client -connect rds-instance-01.cxyz.eu-central-1.rds.amazonaws.com:443 -servername rds-instance-01.cxyz.eu-central-1.rds.amazonaws.com
# → Проверить Subject Alternative Names (SAN) в сертификате

# Проверка с указанием SNI
kubectl run ssl-test --rm -it --image=alpine/openssl -- s_client -connect <external-ip>:443 -servername cloud-db.development.svc.cluster.local
# → Ошибка: hostname mismatch (ожидаемо)
```

**Решение:**
- Использовать промежуточный прокси (Ingress или Sidecar) с TLS Origination
- Для HTTP-сервисов применять ServiceEntry в Istio с настройкой SNI
- Использовать Headless Service с ручными Endpoints вместо ExternalName для HTTP

### Проблема 4: Задержка при обновлении DNS

**Симптом:** После изменения `externalName` в манифесте приложение продолжает обращаться к старому адресу.

**Диагностика:**
```bash
# Проверка текущего значения externalName
kubectl get svc cloud-db -n development -o yaml | grep externalName
# → externalName: new-db.example.com

# Проверка кеширования DNS
kubectl run dns-test --rm -it --image=busybox:1.37 -n development -- nslookup cloud-db.development.svc.cluster.local
# → Может вернуть старый CNAME из кеша
```

**Причины:**
- CoreDNS кеширует ответы с TTL по умолчанию (30 секунд)
- Приложение может иметь собственный DNS-кеш (например, JVM с `networkaddress.cache.ttl`)
- Некоторые библиотеки резолверов игнорируют TTL

**Решение:**
- Уменьшить TTL в настройках CoreDNS (если возможно)
- Перезапустить поды приложения после изменения externalName
- Настроить DNS-кеш приложения на минимальный TTL

## Best Practices

1. **Используйте ExternalName для DNS-имен, не для IP:** Тип ExternalName предназначен для доменных имен. Для статических IP-адресов используйте Service без селектора с ручными Endpoints.

2. **Документируйте порты:** Всегда указывайте `ports` в манифесте — это живая документация для команды, даже если Kubernetes не использует их для маршрутизации:
   ```yaml
   ports:
   - name: postgres
     port: 5432
     protocol: TCP
   ```

3. **Избегайте ExternalName для HTTP-сервисов:** Проблемы с Host-заголовком и SNI делают ExternalName неудобным для HTTP. Используйте Ingress или Service Mesh с TLS Origination.

4. **Контролируйте внешние зависимости:** Трафик через ExternalName не виден в стандартных NetworkPolicy. Для контроля используйте Egress Gateway или Sidecar-прокси.

5. **Мониторьте доступность внешнего ресурса:** ExternalName не имеет built-in health checks. Настройте внешний мониторинг (например, Prometheus Blackbox Exporter) для проверки доступности внешнего ресурса.

6. **Используйте разные имена для разных сред:** Создавайте ExternalName-сервисы с одинаковыми именами в разных namespace для изоляции сред:
   ```yaml
   # namespace: dev
   externalName: db-dev.internal.company.com
   # namespace: prod
   externalName: db-prod.internal.company.com
   ```

7. **Фиксируйте зависимости в Git:** Храните манифесты ExternalName в Git для отслеживания изменений внешних зависимостей и отката при необходимости.

## Edge Cases и ограничения

1. **Кеширование DNS:** TTL ответов CoreDNS и настройки кеширования внутри приложений могут замедлить применение изменений. JVM по умолчанию кеширует DNS навсегда (`networkaddress.cache.ttl=-1`).

2. **Проблемы с виртуальными хостами:** Описанные выше сложности с SNI и `Host` заголовками делают ExternalName непригодным для HTTP-сервисов без промежуточного прокси.

3. **Отсутствие прозрачности для NetworkPolicy:** Трафик **не виден** в стандартных `NetworkPolicy` кластера, так как он идет напрямую на внешние IP, минуя механизмы фильтрации по селекторам.

4. **IPv4/IPv6 несовместимость:** В одностековых IPv6-кластерах могут возникнуть проблемы, если внешний ресурс доступен только по IPv4. CoreDNS может не вернуть корректный CNAME.

5. **Ограничение на формат externalName:** Поле `externalName` принимает только доменное имя, не IP-адрес. Использование IP приведет к ошибке валидации.

6. **Зависимость от CoreDNS:** При сбое CoreDNS все ExternalName-сервисы становятся недоступными. Убедитесь, что CoreDNS работает с репликами и имеет корректные health checks.

7. **Невозможность изменения типа:** Поле `type` Service неизменяемое. Для смены типа требуется удаление и создание сервиса заново.

8. **Ограничения в Service Mesh:** В Istio ExternalName требует настройки DestinationRule для отключения mTLS. Без этого трафик к внешним ресурсам будет зашифрован, что приведет к ошибкам.

## Очистка и откат изменений

```bash
# Просмотр всех ExternalName-сервисов в namespace
kubectl get svc -n development -o wide | grep ExternalName

# Удаление конкретного сервиса
kubectl delete svc cloud-db -n development
# → service "cloud-db" deleted

# Удаление сервиса по манифесту
kubectl delete -f externalname-service.yaml

# Проверка удаления
kubectl get svc cloud-db -n development
# → Error from server (NotFound): services "cloud-db" not found
```

**Важно:** При удалении ExternalName-сервиса все приложения, обращающиеся к нему по имени, потеряют возможность разрешения DNS-имени. Убедитесь, что на сервис нет зависимых ресурсов.

## Дополнительная информация

### Сравнение подходов к внешним ресурсам

| Характеристика | ExternalName | Service без селектора + Endpoints | ServiceEntry (Istio) |
| :--- | :--- | :--- | :--- |
| **Основа** | DNS (CNAME) | IP (DNAT) | L7/L4 Proxy |
| **Цель** | Доменное имя | Статический IP | Управление трафиком |
| **Проксирование** | Нет | Да (kube-proxy) | Да (Envoy Sidecar) |
| **Безопасность** | DNS-уровень | NetworkPolicy (IP) | mTLS, TLS Origination |
| **Health Checks** | Нет | Опционально | Да |

### Ключевые ограничения

- **Кеширование DNS:** TTL ответов CoreDNS и настройки кеширования внутри приложений могут замедлить применение изменений. JVM по умолчанию кеширует DNS навсегда.
- **Проблемы с виртуальными хостами:** Сложности с SNI и `Host` заголовками делают ExternalName непригодным для HTTP-сервисов без промежуточного прокси.
- **Отсутствие прозрачности для NetworkPolicy:** Трафик **не виден** в стандартных `NetworkPolicy` кластера, так как идет напрямую на внешние IP.
- **IPv4/IPv6 несовместимость:** В одностековых IPv6-кластерах могут возникнуть проблемы, если внешний ресурс доступен только по IPv4.

### Диагностика

Для проверки работы сервиса используйте `nslookup` изнутри пода:

```bash
kubectl run dns-test --image=busybox:1.37 --rm -it -- nslookup cloud-db.development.svc.cluster.local

# → Server:    10.96.0.10
# → Address:   10.96.0.10#53
# →
# → cloud-db.development.svc.cluster.local canonical name = rds-instance-01.amazonaws.com.
```

### См. также

- [Обзор Service](./service_overview.md) — общая информация о Service
- [Сводка по типам Service](./service_types_summary.md) — сравнение всех типов Service
- [Headless Service — альтернатива для IP-списков](./service_type_headless.md) — для статических IP-адресов
