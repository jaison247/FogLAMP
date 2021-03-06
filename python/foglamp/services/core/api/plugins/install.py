# -*- coding: utf-8 -*-

# FOGLAMP_BEGIN
# See: http://foglamp.readthedocs.io/
# FOGLAMP_END

import os
import subprocess
import logging
import asyncio
import tarfile
import hashlib

from aiohttp import web
import aiohttp
import async_timeout

from foglamp.common import logger
from foglamp.common.common import _FOGLAMP_ROOT, _FOGLAMP_DATA

__author__ = "Ashish Jabble"
__copyright__ = "Copyright (c) 2019 Dianomic Systems"
__license__ = "Apache 2.0"
__version__ = "${VERSION}"

_help = """
    -------------------------------------------------------------------------------
    | POST             | /foglamp/plugins                                         |
    -------------------------------------------------------------------------------
"""
_TIME_OUT = 120
_CHUNK_SIZE = 1024
_PATH = _FOGLAMP_DATA + '/plugins/' if _FOGLAMP_DATA else _FOGLAMP_ROOT + '/data/plugins/'
_LOGGER = logger.setup(__name__, level=logging.INFO)


async def add_plugin(request: web.Request) -> web.Response:
    """ add plugin

    :Example:
        curl -X POST http://localhost:8081/foglamp/plugins
        data:
            URL - The URL to pull the plugin file from
            format - the format of the file. One of tar or package
            compressed - option boolean this is used to indicate the package is a compressed gzip image
            checksum - the checksum of the file, used to verify correct upload
    """
    try:
        data = await request.json()
        url = data.get('url', None)
        file_format = data.get('format', None)
        compressed = data.get('compressed', None)
        plugin_type = data.get('type', None)
        checksum = data.get('checksum', None)
        if not url or not file_format or not checksum:
            raise TypeError('URL, checksum and format post params are mandatory.')
        if file_format not in ["tar", "deb"]:
            raise ValueError("Invalid format. Must be 'tar' or 'deb'")
        if file_format == "tar" and not plugin_type:
            raise ValueError("Plugin type param is required.")
        if file_format == "tar" and plugin_type not in ['south', 'north', 'filter', 'notificationDelivery',
                                                        'notificationRule']:
            raise ValueError("Invalid plugin type. Must be 'north' or 'south' or 'filter' "
                             "or 'notificationDelivery' or 'notificationRule'")
        if compressed:
            if compressed not in ['true', 'false', True, False]:
                raise ValueError('Only "true", "false", true, false are allowed for value of compressed.')
        is_compressed = ((isinstance(compressed, str) and compressed.lower() in ['true']) or (
            (isinstance(compressed, bool) and compressed is True)))

        # All stuff goes into _PATH
        if not os.path.exists(_PATH):
            os.makedirs(_PATH)

        result = await download([url])
        file_name = result[0]

        # validate checksum with MD5sum
        if validate_checksum(checksum, file_name) is False:
            raise ValueError("Checksum is failed.")

        _LOGGER.debug("Found {} format with compressed {}".format(file_format, is_compressed))
        if file_format == 'tar':
            files = extract_file(file_name, is_compressed)
            _LOGGER.debug("Files {} {}".format(files, type(files)))
            code, msg = copy_file_install_requirement(files, plugin_type, file_name)
            if code != 0:
                raise ValueError(msg)
        else:
            code, msg = install_deb(file_name)
            if code != 0:
                raise ValueError(msg)
    except FileNotFoundError as ex:
        raise web.HTTPNotFound(reason=str(ex))
    except (TypeError, ValueError) as ex:
        raise web.HTTPBadRequest(reason=str(ex))
    except Exception as ex:
        raise web.HTTPException(reason=str(ex))
    else:
        return web.json_response({"message": "{} is successfully downloaded and installed".format(file_name)})


async def get_url(url: str, session: aiohttp.ClientSession) -> str:
    file_name = str(url.split("/")[-1])
    async with async_timeout.timeout(_TIME_OUT):
        async with session.get(url) as response:
            with open(_PATH + file_name, 'wb') as fd:
                async for data in response.content.iter_chunked(_CHUNK_SIZE):
                    fd.write(data)
    return file_name


async def download(urls: list) -> asyncio.gather:
    async with aiohttp.ClientSession() as session:
        tasks = [get_url(url, session) for url in urls]
        return await asyncio.gather(*tasks)


def validate_checksum(checksum: str, file_name: str) -> bool:
    original = hashlib.md5(open(_PATH + file_name, 'rb').read()).hexdigest()
    return True if original == checksum else False


def extract_file(file_name: str, is_compressed: bool) -> list:
    mode = "r:gz" if is_compressed else "r"
    tar = tarfile.open(_PATH + file_name, mode)
    _LOGGER.debug("Extracted to {}".format(_PATH))
    tar.extractall(_PATH)
    return tar.getnames()


def install_deb(file_name: str):
    deb_file_path = "/data/plugins/{}".format(file_name)
    stdout_file_path = "/data/plugins/output.txt"
    cmd = "sudo apt -y install {} > {} 2>&1".format(_FOGLAMP_ROOT + deb_file_path, _FOGLAMP_ROOT + stdout_file_path)
    _LOGGER.debug("CMD....{}".format(cmd))
    ret_code = os.system(cmd)
    _LOGGER.debug("Return Code....{}".format(ret_code))
    msg = ""
    with open("{}".format(_FOGLAMP_ROOT + stdout_file_path), 'r') as fh:
        for line in fh:
            line = line.rstrip("\n")
            msg += line
    _LOGGER.debug("Message.....{}".format(msg))
    # Remove stdout file
    cmd = "{}/extras/C/cmdutil rm {}".format(_FOGLAMP_ROOT, stdout_file_path)
    subprocess.run([cmd], stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)

    # Remove downloaded debian file
    cmd = "{}/extras/C/cmdutil rm {}".format(_FOGLAMP_ROOT, deb_file_path)
    subprocess.run([cmd], stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
    return ret_code, msg


def copy_file_install_requirement(dir_files: list, plugin_type: str, file_name: str) -> tuple:
    py_file = any(f.endswith(".py") for f in dir_files)
    so_1_file = any(f.endswith(".so.1") for f in dir_files)  # regular file
    so_file = any(f.endswith(".so") for f in dir_files)  # symlink file

    if not py_file and not so_file:
        raise FileNotFoundError("Invalid plugin directory structure found, please check the contents of your tar file.")

    if so_1_file:
        if not so_file:
            _LOGGER.error("Symlink file is missing")
            raise FileNotFoundError("Symlink file is missing")
    _dir = []
    for s in dir_files:
        _dir.append(s.split("/")[-1])

    assert len(_dir), "No data found"
    plugin_name = _dir[0]
    _LOGGER.debug("Plugin name {} and Dir {} ".format(plugin_name, _dir))
    plugin_path = "python/foglamp/plugins" if py_file else "plugins"
    full_path = "{}/{}/{}/".format(_FOGLAMP_ROOT, plugin_path, plugin_type)
    dest_path = "{}/{}/".format(plugin_path, plugin_type)

    # Check if plugin dir exists then remove (for cleanup ONLY) otherwise create dir
    if os.path.exists(full_path + plugin_name) and os.path.isdir(full_path + plugin_name):
        cmd = "{}/extras/C/cmdutil rm {}".format(_FOGLAMP_ROOT, dest_path + plugin_name)
        subprocess.run([cmd], stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
    else:
        cmd = "{}/extras/C/cmdutil mkdir {}".format(_FOGLAMP_ROOT, dest_path + plugin_name)
        subprocess.run([cmd], stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)

    # copy plugin files to the relative plugins directory.
    cmd = "{}/extras/C/cmdutil cp {} {}".format(_FOGLAMP_ROOT, _PATH + plugin_name, dest_path)
    subprocess.run([cmd], stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
    _LOGGER.debug("{} File copied to {}".format(cmd, full_path))

    # TODO: FOGL-2760 Handle external dependency for plugins which can be installed via tar file
    # Use case: plugins like opcua, usb4704 (external dep)
    # dht11- For pip packages we have requirements.txt file, as this plugin needs wiringpi apt package to install
    py_req = filter(lambda x: x.startswith('requirement') and x.endswith('.txt'), _dir)
    requirement = list(py_req)
    code = 0
    msg = ""
    if requirement:
        cmd = "{}/extras/C/cmdutil pip3-req {}{}/{}".format(_FOGLAMP_ROOT, _PATH, plugin_name, requirement[0])
        s = subprocess.run([cmd], stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
        code = s.returncode
        msg = s.stderr.decode("utf-8") if code != 0 else s.stdout.decode("utf-8")
        msg = msg.replace("\n", "").strip()
        _LOGGER.debug("Return code {} and msg {}".format(code, msg))

    # Also removed downloaded and extracted tar file
    cmd = "{}/extras/C/cmdutil rm /data/plugins/{}".format(_FOGLAMP_ROOT, file_name)
    subprocess.run([cmd], stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
    cmd = "{}/extras/C/cmdutil rm /data/plugins/{}".format(_FOGLAMP_ROOT, plugin_name)
    subprocess.run([cmd], stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)

    return code, msg
