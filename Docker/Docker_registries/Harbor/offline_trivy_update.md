# Harbor: Оффлайн обновление Trivy

Сканер уязвимостей Trivy требует регулярных обновлений баз. В случае работы Harbor в закрытом контуре (без доступа к интернету), базы необходимо обновлять вручную.

## На компьютере с доступом в интернет
Установите Docker и загрузите базы Trivy:
```bash
apt update && 
apt install docker.io -y
systemctl enable docker --now && 
sudo usermod -aG docker $USER
```
Скачайте образы баз уязвимостей:
```bash
docker pull ghcr.io/aquasecurity/trivy-db:2
docker pull ghcr.io/aquasecurity/trivy-java-db:1
```
Упакуйте скачанные базы:
```bash
# DB
cid=$(docker create ghcr.io/aquasecurity/trivy-db:2)
docker cp $cid:/db db
docker rm $cid

# Java DB
cid=$(docker create ghcr.io/aquasecurity/trivy-java-db:1)
docker cp $cid:/java-db java-db
docker rm $cid

tar czf trivy-db.tgz db
tar czf trivy-java-db.tgz java-db
```
## Перенос на Harbor-хост (закрытый контур) и распаковка
Перенесите файлы `trivy-db.tgz` и `trivy-java-db.tgz` на Harbor-хост, где нет доступа к интернету. Затем распакуйте их в соответствующие директории внутри контейнера `trivy-adapter`:
```bash
sudo mkdir -p /data/trivy-adapter/trivy/db
sudo mkdir -p /data/trivy-adapter/trivy/java-db
sudo tar -xzf trivy-db.tgz -C /data/trivy-adapter/trivy/db
sudo tar -xzf trivy-java-db.tgz -C /data/trivy-adapter/trivy/java-db
sudo chown -R 10000:10000 /data/trivy-adapter/trivy 2>/dev/null || true
docker restart trivy-adapter
```
Таким образом, базы Trivy будут обновлены вручную, и сканер сможет функционировать в оффлайн-режиме.
