# Продвинутая диагностика Service: tcpdump, netshoot, conntrack

## Определения

**Продвинутая диагностика Service** — комплексный подход к отладке сетевых проблем, включающий захват пакетов (tcpdump), эфемерную отладку (netshoot), анализ conntrack и проверку правил kube-proxy. Используется когда стандартных команд kubectl недостаточно для выявления корневой причины проблемы.

**tcpdump** — утилита для захвата и анализа сетевых пакетов. Позволяет видеть реальный трафик на интерфейсе и определять, где пакеты теряются или модифицируются.

**netshoot** - Docker-образ с набором сетевых утилит (curl, wget, nslookup, dig, tcpdump, mtr, iperf и др.) для диагностики сетевых проблем внутри Kubernetes.

**conntrack** - утилита для просмотра и управления таблицей соединений ядра Linux. Показывает, как kube-proxy транслирует адреса.

---

## Основные концепции

### Уровни диагностики

Диагностику Service следует выполнять снизу вверх:

```
Уровень 1: Физическая связность (ping, арпедия)
    |
Уровень 2: DNS резолвинг (nslookup, dig)
    |
Уровень 3: TCP/UDP соединения (telnet, nc, ss)
    |
Уровень 4: NAT и правила (conntrack, iptables/nftables)
    |
Уровень 5: Приложение (curl, HTTP-запросы)
```

---

## Практические сценарии

### Инструмент 1: tcpdump для захвата трафика Service

#### Сценарий: Трафик не доходит до пода

```bash
# Запуск tcpdump в поде для перехвата трафика
kubectl run tcpdump --rm -it --image=nicolaka/netshoot -- bash

# Внутри пода: захват трафика на интерфейсе eth0
tcpdump -i eth0 -nn port 8080

# В другом терминале: обращение к Service
kubectl run curl-test --rm -it --image=curlimages/curl -- curl http://my-service:80

# Результат tcpdump покажет:
# 10.244.1.5.45678 > 10.96.100.50.80: Flags [S]  (SYN - начало соединения)
# 10.244.2.3.80 > 10.244.1.5.45678: Flags [S.] (SYN-ACK - ответ пода)
```

#### Сценарий: Проверка DNAT (трансляции адресов)

```bash
# На узле (или через debug pod с hostNetwork): захват на интерфейсе с ClusterIP
tcpdump -i any -nn host 10.96.100.50

# Покажет:
# Клиент -> 10.96.100.50:80 (ClusterIP)
# kube-proxy делает DNAT -> 10.244.1.5:8080 (Pod IP)
```

#### Сценарий: Проверка hairpin NAT

```bash
# Под обращается к самому себе через ClusterIP
kubectl exec -it <pod-name> -- tcpdump -i eth0 -nn host 10.96.100.50

# Покажет трафик от пода к ClusterIP и обратно через loopback
```

### Инструмент 2: netshoot для комплексной диагностики

#### Запуск netshoot пода

```bash
# Базовый запуск
kubectl run netshoot --rm -it --image=nicolaka/netshoot -- bash

# С сетевым namespace конкретного пода (для отладки проблем в этом поде)
kubectl debug -it <pod-name> --image=nicolaka/netshoot --target=<container-name>
```

#### Диагностика DNS

```bash
# Проверка DNS-резолвинга Service
nslookup my-service.default.svc.cluster.local

# Проверка SRV-записей (для именованных портов)
dig SRV _http._tcp.my-service.default.svc.cluster.local +short

# Проверка CoreDNS напрямую
dig @10.96.0.10 my-service.default.svc.cluster.local +short
```

#### Диагностика TCP-соединений

```bash
# Проверка доступности Service по порту
nc -zv my-service 80

# Проверка доступности конкретного пода
nc -zv 10.244.1.5 8080

# Проверка с таймаутом
nc -zv -w 3 my-service 80
```

#### Диагностика HTTP

```bash
# Полный HTTP-запрос с заголовками
curl -v http://my-service:80/healthz

# С указанием Host-заголовка (для виртуальных хостов)
curl -v -H "Host: my-app.example.com" http://my-service:80

# С таймаутом
curl -v --connect-timeout 5 --max-time 10 http://my-service:80
```

#### Traceroute

```bash
# Маршрут до Service
traceroute my-service

# Маршрут до конкретного пода
traceroute 10.244.1.5
```

### Инструмент 3: conntrack для анализа NAT

#### Просмотр соединений Service

```bash
# Все соединения для конкретного ClusterIP
sudo conntrack -L -p tcp --dport 80 | grep 10.96.100.50

# Пример вывода:
# tcp  6 ESTABLISHED src=10.244.1.5 dst=10.96.100.50 sport=45678 dport=80 
#   src=10.244.2.3 dst=10.244.1.5 sport=8080 dport=45678 [ASSURED]

# Показывает:
# - Исходный трафик: клиент 10.244.1.5 -> ClusterIP 10.96.100.50:80
# - После DNAT: под 10.244.2.3:8080 -> клиент 10.244.1.5:45678
```

#### Статистика conntrack

```bash
# Проверка ошибок conntrack
sudo conntrack -S
# cpu=0 found=123456 invalid=789 lost=42 insert=0 insert_failed=10

# Ключевые поля:
# insert_failed > 0 - проблема с производительностью conntrack
# lost > 0 - соединения теряются из-за переполнения
```

#### Очистка conntrack (осторожно!)

```bash
# Очистка всех записей conntrack (вызывает brief disruption)
sudo conntrack -F

# Очистка записей для конкретного пода
sudo conntrack -D -p tcp --dport 8080 -s 10.244.1.5
```

### Инструмент 4: Проверка правил kube-proxy

#### iptables режим

```bash
# Просмотр правил для конкретного Service
sudo iptables -t nat -L KUBE-SERVICES -n | grep <cluster-ip>

# Просмотр цепочки конкретного сервиса
sudo iptables -t nat -L KUBE-SVC-XXXXX -n

# Просмотр DNAT правил
sudo iptables -t nat -L KUBE-SEP-XXXXX -n
```

#### nftables режим

```bash
# Просмотр правил nftables
sudo nft list table ip kube-proxy

# Просмотр цепочки сервисов
sudo nft list chain ip kube-proxy services
```

#### IPVS режим

```bash
# Просмотр IPVS таблицы
sudo ipvsadm -Ln

# Просмотр с статистикой
sudo ipvsadm -Ln --stats
```

---

## Комплексные сценарии отладки

### Сценарий 1: Service существует, но трафик не проходит

**Алгоритм:**
```bash
# 1. Проверка Service и эндпоинтов
kubectl get svc my-service
kubectl get endpointslice -l kubernetes.io/service-name=my-service
# -> Если эндпоинты пусты - проблема с селектором или readiness

# 2. Проверка DNS
kubectl run test --rm -it --image=busybox:1.37 -- nslookup my-service
# -> Если DNS не работает - проблема с CoreDNS

# 3. Проверка доступности по IP
kubectl run test --rm -it --image=curlimages/curl -- curl -v http://<cluster-ip>:80
# -> Если по IP работает, но по имени нет - проблема с DNS

# 4. Проверка conntrack
sudo conntrack -L -p tcp --dport 80 | grep <cluster-ip>
# -> Если conntrack пуст - проблема с правилами kube-proxy

# 5. Проверка правил kube-proxy
sudo iptables -t nat -L KUBE-SERVICES -n | grep <cluster-ip>
# -> Если правило отсутствует - kube-proxy не запрограммировал его
```

### Сценарий 2: Медленные ответы от Service

**Алгоритм:**
```bash
# 1. Проверка latencies с помощью curl
kubectl run test --rm -it --image=curlimages/curl -- curl -w "time_total: %{time_total}\ntime_connect: %{time_connect}\ntime_starttransfer: %{time_starttransfer}\n" -o /dev/null -s http://my-service:80

# 2. Проверка conntrack (задержки на NAT)
sudo conntrack -L -p tcp --dport 80 | grep <cluster-ip>
# -> Если много соединений в состоянии SYN_RECV - проблема с backlog

# 3. Проверка загрузки подов
kubectl top pods -l app=my-app

# 4. Проверка NetworkPolicy (политики могут добавлять задержки)
kubectl get networkpolicy -n <namespace>
```

### Сценарий 3: 502 Bad Gateway от Service

**Алгоритм:**
```bash
# 1. Проверка готовности подов
kubectl get pods -l app=my-app
# -> Если READY 0/1 - поды не прошли readinessProbe

# 2. Проверка логов пода
kubectl logs -l app=my-app --tail=50
# -> Поиск ошибок в приложении

# 3. Проверка EndpointSlices
kubectl get endpointslice -l kubernetes.io/service-name=my-service -o yaml
# -> Если поды в списке, но 502 - проблема в приложении

# 4. Проверка tcpdump
kubectl run tcpdump --rm -it --image=nicolaka/netshoot -- tcpdump -i eth0 -nn port 80
# -> Если SYN-ACK не приходит - под не отвечает
```

---

## Шпаргалка команд

### Проверка состояния Service

```bash
# Быстрая проверка
kubectl get svc,endpointslice -l app=my-app
kubectl describe svc my-service
kubectl get events --field-selector involvedObject.name=my-service
```

### Проверка DNS

```bash
kubectl run test --rm -it --image=busybox:1.37 -- nslookup my-service.default.svc.cluster.local
kubectl run test --rm -it --image=busybox:1.37 -- dig SRV _http._tcp.my-service.default.svc.cluster.local +short
```

### Проверка сетевой связности

```bash
kubectl run test --rm -it --image=curlimages/curl -- curl -v http://my-service:80
kubectl run test --rm -it --image=nicolaka/netshoot -- nc -zv my-service 80
kubectl run test --rm -it --image=nicolaka/netshoot -- traceroute my-service
```

### Проверка conntrack

```bash
sudo conntrack -L -p tcp --dport 80 | grep <cluster-ip>
sudo conntrack -S
sudo conntrack -C
```

### Проверка правил kube-proxy

```bash
# iptables
sudo iptables -t nat -L KUBE-SERVICES -n | grep <cluster-ip>

# nftables
sudo nft list table ip kube-proxy

# IPVS
sudo ipvsadm -Ln
```

---

## Best Practices

1. **Всегда начинайте с kubectl** - проверьте Service, EndpointSlice, поды перед использованием tcpdump
2. **Используйте netshoot** вместо установки утилит в production-поды
3. **Запускайте tcpdump в отдельном поде** - не в целевом приложении
4. **Сохраняйте вывод** - `tcpdump -w /tmp/capture.pcap` для последующего анализа в Wireshark
5. **Очищайте conntrack осторожно** - `conntrack -F` вызывает brief disruption
6. **Документируйте** - записывайте шаги диагностики для повторного использования
7. **Используйте kubectl debug** для эфемерных контейнеров в Kubernetes 1.25+

---

## Дополнительная информация

### Связанные темы

- **Network Troubleshooting:** [Kubernetes Network Troubleshooting](../Network/kubernetes_network_troubleshooting.md) - общий подход
- **conntrack:** [NetworkPolicy Performance](../Network/NetworkPolicy/performance.md) - настройка conntrack
- **kube-proxy:** [kube-proxy](../Network/kube-proxy.md) - детали режимов работы
- **tcpdump в Wireshark:** [Wireshark Service Mesh](../../../../Networking/ServicesAndTools/Wireshark/service_mesh_analysis.md) - анализ Service Mesh

### См. также

- [Обзор Service](./service_overview.md) - архитектура и механизмы
- [Отказоустойчивость Service](./service_failure_modes.md) - failure modes
- [NetworkPolicy + Service](./service_network_policy_integration.md) - паттерны изоляции
