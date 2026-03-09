# nftables: тестирование правил файрвола

## Проблема

Требуется проверить, что файрвол корректно блокирует все порты, включая те, которые не прослушиваются сервисами.

## Инструменты

- `netcat` (nc) — открытие портов для тестирования
- `nmap` — сканирование портов
- `netstat` — проверка локальных listening-портов

## Подготовка

```bash
# На тестируемом сервере
apt install netcat net-tools

# На сканирующей машине
apt install nmap
```

## Проверка локальных портов

```bash
# UDP порты
netstat -lu

# TCP порты
netstat -lt
```

## Открытие порта для тестирования

```bash
# UDP порт 100
echo "PORT UDP 100 opened" | nc -lu 100

# TCP порт 300
echo "PORT TCP 300 opened" | nc -lt 300
```

## Сканирование с удалённой машины

```bash
# TCP порт 100
nmap -v 172.30.0.40 -T5 -sT -p100

# UDP порт 100
nmap -v 172.30.0.40 -T5 -sU -p100
```

---

## Скрипт для открытия диапазона портов

Файл `openport.sh`:

```bash
#!/bin/bash
PROTOCOL=$1
START_PORT=$2
END_PORT=$3

if [[ $# != 3 ]]
then
    echo -e "Script usage:\nopenport.sh <UDP|TCP> <start port> <end port>"
    exit 1
fi

x=$START_PORT
while [ $x -le $END_PORT ]
do
    if [ $PROTOCOL == "UDP" ]
    then
        echo "PORT UDP $x opened" | nc -lu $x &
    elif [ $PROTOCOL == "TCP" ]
    then
        echo "PORT TCP $x opened" | nc -lt $x &
    else
        echo "ERROR: invalid protocol"
        exit 1
    fi
    echo "Open port $PROTOCOL: $x"
    x=$(( $x + 1 ))
done
```

### Пример использования

```bash
# Открыть TCP порты 1-30 на сервере
./openport.sh TCP 1 30

# Сканировать с другой машины
nmap -v 172.30.0.40 -T5 -sT -p1-30
```

**Важно:** Не открывайте более 1000 портов одновременно — сервер может потерять стабильность.
