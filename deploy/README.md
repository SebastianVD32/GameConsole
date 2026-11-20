# Publicar GameConsole en Internet

Los jugadores solo necesitan abrir la URL HTTPS de GameConsole. El administrador
configura el alojamiento una vez; los visitantes no instalan Docker, Python ni Prolog.
GitHub conserva el código y las imágenes, pero no ejecuta estos tres servidores.

## Producción

- Aplicación: [GameConsole](https://gameconsole-nkx6wjmnfl4di.eastus.cloudapp.azure.com).
- Video: [demostración en Google Drive](https://drive.google.com/file/d/17kTfgxgQDRCX1NYrtCkBt1XXv0sd_4mm/view?usp=sharing).
- Azure: grupo `rg-gameconsole`, VM `gameconsole`, región East US.
- Máquina instalada: `Standard_F1as_v7`, 1 CPU, 4 GB RAM y SSD de 32 GB.
- Versión verificada el 20 de noviembre de 2026:
  `75d9bf70f08f8c0639f1f44ad25c86187d6db3ef`.
- [Despliegue automático verificado](https://github.com/SebastianVD32/GameConsole/actions/runs/44820870018).

Cada despliegue posterior instala la etiqueta SHA del commit verificado por CI.
La versión vigente se consulta en GitHub Actions, entorno `production`, y en
`GAMECONSOLE_TAG` del archivo `/opt/gameconsole/deploy/.env` del servidor.

## Entrega desde GitHub

El workflow de `main` prueba Python, Prolog, JavaScript y la integración con
GameStats. Después construye y vuelve a probar las tres imágenes de la entrega:

| Servicio | Imagen |
|---|---|
| Consola y Prolog | `ghcr.io/sebastianvd32/gameconsole` |
| Ingestión Go | `ghcr.io/sebastianvd32/gameconsole-gamestats-go` |
| Análisis Scala | `ghcr.io/sebastianvd32/gameconsole-gamestats-scala` |

Las tres usan la misma etiqueta `sha-<commit completo de GameConsole>`.
`latest` se actualiza tras las verificaciones. Para una instalación reproducible,
selecciona la etiqueta SHA indicada en el resumen del workflow, no mezcles versiones.
Los paquetes de GameStats originales no se modifican: estas imágenes contienen
la revisión compatible definida en `GAMESTATS_REF` del workflow.

El repositorio y los paquetes pueden seguir privados. El servidor necesita permiso
para descargarlos; los jugadores no necesitan acceso a GitHub. Si el proveedor no
puede leer GHCR, conecta los repositorios y construye desde los Dockerfiles.
No guardes tokens ni contraseñas en el repositorio.

## Alojamiento en Azure for Students

La opción preparada ejecuta los tres servicios en una VM Ubuntu y usa Caddy
para dar acceso HTTPS. Azure aporta un nombre DNS `*.cloudapp.azure.com`;
no es necesario comprar un dominio. Solo se publican los puertos 80 y 443.
El puerto SSH se limita a la IP del administrador. Go y Scala permanecen privados.

`azure/main.bicep` define VM, disco SSD de 32 GB, red, firewall e IP pública.
`azure/cloud-init.yaml` instala Docker y Compose. La plantilla conserva como valor
predeterminado `Standard_B2als_v2`; para reproducir la instalación actual se debe
pasar `vmSize=Standard_F1as_v7`, como en el comando siguiente. Comprobar cuota,
disponibilidad y costo antes de crear recursos. Azure Students puede aplicar el crédito disponible,
pero el servicio consume recursos mientras está encendido. Revisar el saldo en
[Azure Education Hub](https://portal.azure.com/#view/Microsoft_Azure_Education/EducationMenuBlade/~/overview).

Los siguientes comandos son para el administrador, no para los jugadores.
La creación de infraestructura requiere aprobación del presupuesto. Una vez
aprobada, desde PowerShell con Azure CLI autenticada:

```powershell
$group = 'rg-gameconsole'
$region = 'eastus' # Cambiar por la región con cuota y disponibilidad verificadas.
$publicKey = Get-Content "$env:USERPROFILE/.ssh/gameconsole.pub" -Raw
$adminCidr = 'IP_PUBLICA_DEL_ADMIN/32'
az group create --name $group --location $region
az deployment group create --resource-group $group --template-file deploy/azure/main.bicep --parameters vmSize=Standard_F1as_v7 sshPublicKey="$publicKey" adminCidr="$adminCidr"
az deployment group show --resource-group $group --name main --query properties.outputs -o json
```

Crear previamente una clave SSH con `ssh-keygen -t ed25519`, guardando la clave
privada fuera del repositorio. Usar el nombre DNS devuelto por Azure para conectarse.
Esperar a que `sudo cloud-init status --wait` finalice en el servidor.

Copiar esta carpeta `deploy` a `/opt/gameconsole/deploy` de la VM. Configurar en
`/opt/gameconsole/deploy/.env` únicamente valores no secretos:

```dotenv
GAMECONSOLE_TAG=sha-COMMIT_COMPLETO_PUBLICADO
GAMECONSOLE_DOMAIN=NOMBRE_DNS_DEVUELTO_POR_AZURE
IMAGE_OWNER=sebastianvd32
```

Para paquetes privados, autenticar Docker en GHCR en el servidor con un token
con permiso de lectura de paquetes usando `docker login --password-stdin`.
También se puede descargar las imágenes en una máquina autorizada y transferir
un archivo creado por `docker save` mediante SSH; en Azure se importa con
`sudo docker load`. Esta alternativa no copia credenciales GitHub al servidor.

Desde `/opt/gameconsole/deploy`:

```sh
sudo docker compose --env-file .env -f compose.yaml -f azure/compose.yaml up -d --wait
```

Si se usó `docker load` sin autenticación GHCR, agregar `--pull never` al comando.
Caddy debe poder descargar su imagen pública. Sus certificados, la cola arcade y
los resultados Scala se guardan en volúmenes Docker en el disco de la VM.
La URL pública será `https://NOMBRE_DNS_DEVUELTO_POR_AZURE`.

## Actualizaciones y costos

El workflow `Deploy Azure` actualiza la aplicación automáticamente después de
que CI/CD termine correctamente en `main`. No despliega los pull requests.
Usa OIDC con la identidad `gameconsole-github-deploy`, limitada a consultar y
 ejecutar comandos en la VM. Transfiere un paquete temporal con las tres imágenes,
serializa las actualizaciones, espera la salud de Compose y comprueba el acceso HTTPS.
Si falla, intenta recuperar la configuración y las imágenes de la versión anterior.
No crea nuevas máquinas ni cambia su tamaño.

La identidad federada, su rol limitado y las variables `AZURE_CLIENT_ID`,
`AZURE_TENANT_ID` y `AZURE_SUBSCRIPTION_ID` ya están configuradas para este repositorio.
Una instalación en otra cuenta debe configurar su propia identidad OIDC y concederle
el acceso a su VM; no se deben copiar claves ni contraseñas al código.

Las actualizaciones reinician los servicios. Integrar cambios en `main` cuando no
haya partidas ni demostraciones en curso. Para una recuperación manual, cargar
las tres imágenes de una versión anterior, seleccionar su etiqueta SHA en `.env`
y ejecutar Compose; no eliminar los volúmenes.

El grupo tiene un presupuesto mensual de USD 60 con alertas. Las alertas no
apagan la VM ni constituyen un límite de gasto. El consumo depende del tiempo
encendido, el tráfico, las operaciones y los demás recursos de la cuenta.

Para detener el cómputo sin borrar datos:

```powershell
az vm deallocate --resource-group rg-gameconsole --name gameconsole
```

El disco y la IP pueden seguir generando consumo con la VM detenida. Volver a
encenderla con `az vm start --resource-group rg-gameconsole --name gameconsole`.
Los contenedores tienen reinicio automático. Hacer copias de los volúmenes antes
de eliminar el grupo de recursos, pues eliminarlo también elimina el disco.

## Comprobación del enlace

El administrador verifica la entrega con:

```text
python scripts/smoke_test.py https://DOMINIO-DE-LA-CONSOLA --matches 4 --moves 6
```

Abre también los tres juegos en pestañas distintas y `/estadisticas`; juega hasta
terminar una partida de cada tipo y comprueba el resultado oficial y los contadores.
La prueba de humo crea partidas reales de verificación y modifica las estadísticas.

El disco conserva los eventos arcade y los resultados de Scala. El tablero de
ajedrez vive en memoria y se pierde si la consola se reinicia; Go también mantiene
su resumen operativo en memoria. Los juegos arcade no recuperan su tablero al
recargar la pestaña. No desplegar nuevas versiones durante una demostración.

## Alternativa con servidor Docker

Un servidor Linux con Docker puede ejecutar `compose.yaml` de esta carpeta.
Configura `GAMECONSOLE_TAG=sha-<commit completo>` y autentica Docker en GHCR si los
paquetes son privados. Ejecuta desde la raíz del repositorio:

```text
docker compose -f deploy/compose.yaml up -d --wait
```

La consola se publica solo en `127.0.0.1:5000`. El administrador debe colocar un
proxy HTTPS delante para obtener una URL pública. No publicar los puertos de
GameStats. `verify.compose.yaml` expone sus puertos únicamente para pruebas locales.

La URL de producción y la ejecución verificada figuran al inicio de esta guía.
La versión actual puede cambiar con cada actualización aprobada en `main`.
