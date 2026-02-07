# witr - Узнай, почему процесс запущен

## Определения

`witr` (Why Is That Running) — это утилита командной строки для Linux, которая помогает быстро понять, почему запущен тот или иной процесс. Она объединяет информацию из `ps`, `ss` и `systemd`, чтобы предоставить единую, понятную картину о процессе, его родителях и сетевых портах, которые он слушает.

### Основные концепции

Ключевая особенность `witr` — это построение **дерева зависимостей** процесса. Вместо того чтобы вручную искать PID, затем проверять, какой сервис его запустил, и какие порты он слушает, `witr` делает это автоматически.

Она показывает цепочку вызовов, например:
`systemd (pid 1) → angie (pid 35980) → angie (pid 35981)`

Это мгновенно дает понять, что процесс был запущен не вручную, а является дочерним процессом сервиса, управляемого `systemd`.

### Практические сценарии

### Установка

```bash
# Инструкции по установке с GitHub
# (необходимо добавить актуальные шаги после проверки)
```
Ссылка на проект: [https://github.com/pranshuparmar/witr](https://github.com/pranshuparmar/witr)

### Примеры использования

#### Поиск по имени процесса

Если несколько процессов совпадают по имени, `witr` предложит выбрать конкретный PID.

```bash
root@dns:~# witr angie
Multiple matching processes found:

[1] angie (pid 35980)
    angie: master process v1.11.2 #1 [/usr/sbin/angie -c /etc/angie/angie.conf]
[2] angie (pid 35981)
    angie: worker process #1

Re-run with:
  witr --pid <pid>
```

#### Анализ процесса по PID

Это основной и самый полезный сценарий. `witr` показывает полную сводку о процессе.

```bash
root@dns:~# witr --pid 35981
Target      : angie
# Это воркер, которого породил мастер-процесс (forked)
Process     : angie (pid 35981) {forked} 
User        : angie
Command     : angie: worker process #1
Started     : 6 days ago (Wed 2026-01-21 15:56:34 +00:00)
Restarts    : 1

# Killer-фича: видно, кто породил процесс
Why It Exists :
  systemd (pid 1) → angie (pid 35980) → angie (pid 35981)

Source      : systemd
Working Dir : /

# Сразу видны порты, которые слушает процесс
Listening   : 0.0.0.0:44301
              0.0.0.0:443
              [::]:443
              0.0.0.0:80

# Предупреждения безопасности
Warnings    :
  • Process is listening on a public interface
  • Process is running from a suspicious working directory: /
```

#### Поиск процесса по порту

Если вы видите занятый порт и хотите понять, какой процесс его использует.

```bash
root@dns:~# witr --port 44301
Multiple matching processes found:

[1] angie (pid 35980)
    angie: master process v1.11.2 #1 [/usr/sbin/angie -c /etc/angie/angie.conf]
[2] angie (pid 35981)
    angie: worker process #1

Re-run with:
  witr --pid <pid>
```
