from dataclasses import dataclass
from typing import Dict
import datetime
import os
import time

from telethon.client.telegramclient import TelegramClient

from encryption import *
from ufid import ufid
import storage

@dataclass
class TgfsFile:
    ufid: str
    file_name: str
    encrypted_file_size: int # In bytes.
    num_chunks: int
    time: int # Unix timestamp.

    def __str__(self):
        return f"UFID: {self.ufid}\nFile name: {self.file_name}\nEncrypted file size (bytes): {self.encrypted_file_size}\nTimestamp: {datetime.datetime.fromtimestamp(self.time).strftime('%Y-%m-%d %H:%M:%S')}"

async def store_file(client:TelegramClient, file_path:str, encryption_password:str) -> TgfsFile:
    file_ufid = ufid(file_path)
    num_chunks = storage.get_num_chunks(file_path)
    tgfs_file = TgfsFile(
        ufid=file_ufid,
        file_name=os.path.basename(file_path),
        encrypted_file_size=os.path.getsize(file_path),
        num_chunks=num_chunks,
        time=int(time.time())
    )
    for i in range(num_chunks):
        # Store a chunk in a local file.
        chunk = encrypt(storage.get_chunk(file_path, i), encryption_password)
        chunk_file_path = storage.save_chunk(file_ufid, i, chunk)

        # Send the chunk to Telegram.
        file_caption = f"tgfs {file_ufid} chunk {i+1}/{num_chunks} {os.path.basename(file_path)}"
        await client.send_message(
            "me",
            file_caption,
            file=chunk_file_path
        )
        
        # Remove the chunk file locally.
        os.remove(chunk_file_path)
        print(f"Uploaded chunk {i+1}/{num_chunks}.")
    
    return tgfs_file

async def lookup_file(client:TelegramClient, query_file_name:str) -> Dict[str, TgfsFile]:
    files: Dict[str, TgfsFile] = {}
    search_query = f"tgfs {query_file_name} chunk"

    async for message in client.iter_messages("me", search=search_query):
        msg = message.message
        file_ufid = msg[5:69]
        chunk_size = message.document.size
        chunk_index = msg[70:70+msg[70:].index("/")]
        num_chunks = int(msg[70+msg[70:].index("/")+1:76+msg[76:].index(" ")])
        file_name = msg[76+msg[76:].index(" ")+1:]
        chunk_time = int(message.date.timestamp())

        if file_ufid not in files:
            files[file_ufid] = TgfsFile(
                ufid=file_ufid,
                file_name=file_name,
                encrypted_file_size=chunk_size,
                num_chunks=num_chunks,
                time=chunk_time
            )
        else:
            files[file_ufid].encrypted_file_size += chunk_size
            if chunk_time < files[file_ufid].time:
                files[file_ufid].time = chunk_time
    
    return files

async def download_file(client:TelegramClient, tgfs_file:TgfsFile, decryption_password:str) -> bytes:
    # Download file chunk-by-chunk and stream to a file locally.
    for i in range(tgfs_file.num_chunks):
        search_query = f"tgfs {tgfs_file.ufid} chunk {i+1}/{tgfs_file.num_chunks} {tgfs_file.file_name}"
        # Store all message objects in a list.
        messages = await client.get_messages("me", search=search_query)
        # Sort messages by the chunk index of each.
        messages.sort(key=lambda m: int(m.message[76:76+m.message[76:].index("/")]))
        # Download each chunk and decrypt it.
        for message in messages:
            chunk_file_name = await message.download_media()
            with open(chunk_file_name, "rb") as chunk_file:
                chunk_data = decrypt(chunk_file.read(), decryption_password)
                with open(tgfs_file.file_name, "ab") as file:
                    file.write(chunk_data)
            os.remove(chunk_file_name)
        print(f"Finished downloading chunk {i+1}/{tgfs_file.num_chunks} of file `{tgfs_file.file_name}`.")
