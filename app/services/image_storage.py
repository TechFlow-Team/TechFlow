"""Private, S3-ready product image storage with a local development backend."""
from io import BytesIO
from pathlib import Path
import re
from urllib.parse import urlsplit
from uuid import uuid4

import boto3
from flask import current_app, url_for
from PIL import Image, ImageOps, UnidentifiedImageError


class ImageStorageError(ValueError):
    pass


MAX_IMAGE_BYTES = 6 * 1024 * 1024
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}


def save_product_image(upload) -> str:
    if not upload or not getattr(upload, "filename", ""):
        raise ImageStorageError("Chọn một ảnh JPEG, PNG hoặc WebP để tải lên.")
    raw = upload.stream.read(MAX_IMAGE_BYTES + 1)
    if not raw or len(raw) > MAX_IMAGE_BYTES:
        raise ImageStorageError("Ảnh phải nhỏ hơn 6 MB.")
    try:
        with Image.open(BytesIO(raw)) as source:
            if source.format not in ALLOWED_FORMATS or source.width * source.height > 24_000_000:
                raise ImageStorageError("Chỉ nhận ảnh JPEG, PNG hoặc WebP, tối đa 24 megapixel.")
            source.verify()
        with Image.open(BytesIO(raw)) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
            image.thumbnail((2400, 2400), Image.Resampling.LANCZOS)
            output = BytesIO()
            image.save(output, format="WEBP", quality=86, method=6)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise ImageStorageError("Tệp tải lên không phải ảnh hợp lệ.") from None

    key = f"products/{uuid4().hex}.webp"
    body = output.getvalue()
    if current_app.config["UPLOAD_STORAGE"] == "s3":
        bucket = current_app.config["S3_BUCKET"]
        if not bucket:
            raise ImageStorageError("Chưa cấu hình S3_BUCKET cho nơi lưu ảnh production.")
        try:
            _s3().put_object(Bucket=bucket, Key=key, Body=body, ContentType="image/webp",
                             CacheControl="private, max-age=3600")
        except Exception:
            current_app.logger.exception("Could not store product image in S3")
            raise ImageStorageError("Chưa lưu được ảnh lên S3. Kiểm tra quyền IAM của máy chủ.") from None
        region = current_app.config["AWS_REGION"]
        return f"https://{bucket}.s3.{region}.amazonaws.com/{key}"

    path = Path(current_app.config["PRODUCT_UPLOAD_DIR"]) / Path(key).name
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    except OSError:
        current_app.logger.exception("Could not store product image locally")
        raise ImageStorageError("Không lưu được ảnh trong thư mục uploads. Hãy kiểm tra Docker volume và quyền ghi.") from None
    return url_for("static", filename=f"uploads/products/{path.name}")


def display_product_image(value):
    if not value:
        return ""
    if current_app.config["UPLOAD_STORAGE"] != "s3":
        return value
    bucket = current_app.config["S3_BUCKET"]
    region = current_app.config["AWS_REGION"]
    parts = urlsplit(value)
    expected_host = f"{bucket}.s3.{region}.amazonaws.com"
    if not bucket or parts.scheme != "https" or parts.hostname != expected_host or not parts.path.startswith("/products/"):
        return value
    try:
        return _s3().generate_presigned_url("get_object", Params={"Bucket": bucket, "Key": parts.path.lstrip("/")}, ExpiresIn=3600)
    except Exception:
        current_app.logger.exception("Could not sign product image URL")
        return ""


def placeholder_for(product):
    name = ((getattr(getattr(product, 'category', None), 'name', '') or '')).lower()
    slug = ('laptop' if 'laptop' in name else 'monitor' if 'màn hình' in name else 'components' if 'linh kiện' in name else 'peripherals' if 'ngoại vi' in name else 'network' if 'mạng' in name else 'accessory' if 'phụ kiện' in name else 'default')
    return url_for('static', filename=f'images/placeholders/{slug}.svg')


def product_image_src(product):
    if getattr(product, 'image_url', None):
        return display_product_image(product.image_url)
    return placeholder_for(product)


def delete_product_image(value):
    if not value:
        return
    if value.startswith("/static/uploads/products/"):
        name = value.rsplit("/", 1)[-1]
        if re.fullmatch(r"[a-f0-9]{32}\.webp", name):
            (Path(current_app.config["PRODUCT_UPLOAD_DIR"]) / name).unlink(missing_ok=True)
        return
    bucket = current_app.config["S3_BUCKET"]
    region = current_app.config["AWS_REGION"]
    parts = urlsplit(value)
    if (current_app.config["UPLOAD_STORAGE"] == "s3" and bucket and parts.scheme == "https"
            and parts.hostname == f"{bucket}.s3.{region}.amazonaws.com" and parts.path.startswith("/products/")):
        try:
            _s3().delete_object(Bucket=bucket, Key=parts.path.lstrip("/"))
        except Exception:
            current_app.logger.exception("Could not delete replaced product image")


def s3_image_origin(app):
    bucket, region = app.config.get("S3_BUCKET"), app.config.get("AWS_REGION")
    if app.config.get("UPLOAD_STORAGE") == "s3" and bucket and region:
        return f"https://{bucket}.s3.{region}.amazonaws.com"
    return None


def _s3():
    return boto3.client("s3", region_name=current_app.config["AWS_REGION"])
