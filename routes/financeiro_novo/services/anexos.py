from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError
from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename


MIME_PDF = "application/pdf"
TAMANHO_MAXIMO_ENTRADA = 20 * 1024 * 1024
MAXIMO_PAGINAS = 100
MAXIMO_LADO_IMAGEM = 1800
QUALIDADE_JPEG = 68
MAXIMO_LADO_IMAGEM_PDF = 1800
QUALIDADE_JPEG_PDF = 65


class AnexoInvalido(ValueError):
    pass


@dataclass(frozen=True)
class AnexoCanonico:
    conteudo: bytes
    nome_original: str
    mime_original: str
    sha256_original: str
    sha256_canonico: str
    tamanho_original: int
    tamanho_canonico: int
    paginas: int
    compressao_aplicada: bool
    assinatura_digital_detectada: bool

    @property
    def mime_canonico(self):
        return MIME_PDF


def _imagem_rgb_otimizada(imagem: Image.Image, maximo_lado: int) -> Image.Image:
    imagem = ImageOps.exif_transpose(imagem)
    imagem.thumbnail((maximo_lado, maximo_lado), Image.Resampling.LANCZOS)
    if imagem.mode not in {"RGB", "L"}:
        fundo = Image.new("RGB", imagem.size, "white")
        if "A" in imagem.getbands():
            fundo.paste(imagem, mask=imagem.getchannel("A"))
        else:
            fundo.paste(imagem.convert("RGB"))
        imagem = fundo
    else:
        imagem = imagem.convert("RGB")
    return imagem


def _imagem_para_jpeg(imagem: Image.Image) -> bytes:
    imagem = _imagem_rgb_otimizada(imagem, MAXIMO_LADO_IMAGEM)

    saida = BytesIO()
    imagem.save(
        saida,
        format="JPEG",
        quality=QUALIDADE_JPEG,
        optimize=True,
        progressive=True,
    )
    return saida.getvalue()


def _imagens_para_pdf(conteudo: bytes) -> tuple[bytes, int]:
    try:
        origem = Image.open(BytesIO(conteudo))
    except (UnidentifiedImageError, OSError) as exc:
        raise AnexoInvalido("O arquivo não é uma imagem válida.") from exc

    quadros = getattr(origem, "n_frames", 1)
    if quadros > MAXIMO_PAGINAS:
        raise AnexoInvalido(f"O anexo excede o limite de {MAXIMO_PAGINAS} páginas.")

    pdf = BytesIO()
    documento = canvas.Canvas(pdf, pagesize=A4, pageCompression=1)
    pagina_largura, pagina_altura = A4
    margem = 24
    for indice in range(quadros):
        origem.seek(indice)
        jpeg = _imagem_para_jpeg(origem.copy())
        imagem = Image.open(BytesIO(jpeg))
        largura, altura = imagem.size
        escala = min(
            (pagina_largura - 2 * margem) / largura,
            (pagina_altura - 2 * margem) / altura,
        )
        destino_largura = largura * escala
        destino_altura = altura * escala
        x = (pagina_largura - destino_largura) / 2
        y = (pagina_altura - destino_altura) / 2
        documento.drawImage(
            ImageReader(BytesIO(jpeg)),
            x,
            y,
            destino_largura,
            destino_altura,
            preserveAspectRatio=True,
            mask="auto",
        )
        documento.showPage()
    documento.save()
    return pdf.getvalue(), quadros


def _otimizar_imagens_pdf(escritor: PdfWriter) -> int:
    substituidas = 0
    for pagina in escritor.pages:
        try:
            imagens = list(pagina.images)
        except Exception:
            continue
        for imagem_pdf in imagens:
            try:
                imagem = _imagem_rgb_otimizada(imagem_pdf.image, MAXIMO_LADO_IMAGEM_PDF)
                imagem_pdf.replace(imagem, quality=QUALIDADE_JPEG_PDF, optimize=True)
                substituidas += 1
            except Exception:
                # Imagens inline ou formatos incomuns permanecem intactos; o
                # restante do PDF ainda passa pela compactação estrutural.
                continue
    return substituidas


def _pdf_otimizado(conteudo: bytes) -> tuple[bytes, int, bool, bool]:
    try:
        leitor = PdfReader(BytesIO(conteudo), strict=True)
    except Exception as exc:
        raise AnexoInvalido("O arquivo não é um PDF válido.") from exc

    if leitor.is_encrypted:
        raise AnexoInvalido("PDF protegido por senha não é permitido.")
    if not leitor.pages:
        raise AnexoInvalido("O PDF não possui páginas.")
    if len(leitor.pages) > MAXIMO_PAGINAS:
        raise AnexoInvalido(f"O anexo excede o limite de {MAXIMO_PAGINAS} páginas.")

    assinatura = False
    try:
        raiz = leitor.trailer["/Root"]
        acroform = raiz.get("/AcroForm")
        acroform = acroform.get_object() if acroform else None
        for campo_ref in (acroform or {}).get("/Fields", []):
            campo = campo_ref.get_object()
            if campo.get("/FT") == "/Sig":
                assinatura = True
                break
    except Exception:
        assinatura = False

    # Regravar um PDF assinado invalida sua assinatura. Nesse caso, o próprio
    # PDF original já é o formato canônico e deve ser preservado sem alteração.
    if assinatura:
        return conteudo, len(leitor.pages), True, False

    escritor = PdfWriter()
    for pagina in leitor.pages:
        escritor.add_page(pagina)
        try:
            escritor.pages[-1].compress_content_streams()
        except Exception:
            pass
    _otimizar_imagens_pdf(escritor)
    escritor.compress_identical_objects(remove_duplicates=True, remove_unreferenced=True)
    escritor.add_metadata({"/Producer": "PRUMAT Financeiro Novo"})
    saida = BytesIO()
    escritor.write(saida)
    otimizado = saida.getvalue()
    if len(otimizado) >= len(conteudo):
        return conteudo, len(leitor.pages), assinatura, False
    return otimizado, len(leitor.pages), assinatura, True


def normalizar_anexo(arquivo: FileStorage) -> AnexoCanonico:
    """Converte foto ou PDF em um PDF canônico otimizado e validado."""
    if not arquivo or not arquivo.filename:
        raise AnexoInvalido("Selecione um arquivo.")

    nome_original = secure_filename(arquivo.filename) or "anexo"
    conteudo = arquivo.stream.read(TAMANHO_MAXIMO_ENTRADA + 1)
    arquivo.stream.seek(0)
    if not conteudo:
        raise AnexoInvalido("O arquivo está vazio.")
    if len(conteudo) > TAMANHO_MAXIMO_ENTRADA:
        raise AnexoInvalido("O arquivo excede o limite de 20 MB.")

    mime_original = (arquivo.mimetype or "application/octet-stream").lower()
    assinatura_digital = False
    compressao_aplicada = True
    if conteudo.startswith(b"%PDF-"):
        canonico, paginas, assinatura_digital, compressao_aplicada = _pdf_otimizado(conteudo)
    else:
        canonico, paginas = _imagens_para_pdf(conteudo)

    # Validação final independente do tipo de origem.
    try:
        validacao = PdfReader(BytesIO(canonico), strict=True)
        if len(validacao.pages) != paginas:
            raise AnexoInvalido("Falha ao validar a quantidade de páginas do PDF.")
    except AnexoInvalido:
        raise
    except Exception as exc:
        raise AnexoInvalido("Não foi possível validar o PDF normalizado.") from exc

    return AnexoCanonico(
        conteudo=canonico,
        nome_original=nome_original,
        mime_original=mime_original,
        sha256_original=sha256(conteudo).hexdigest(),
        sha256_canonico=sha256(canonico).hexdigest(),
        tamanho_original=len(conteudo),
        tamanho_canonico=len(canonico),
        paginas=paginas,
        compressao_aplicada=compressao_aplicada,
        assinatura_digital_detectada=assinatura_digital,
    )


def nome_objeto_pdf(arquivo_id: str) -> str:
    return str(Path("financeiro_novo") / arquivo_id[:2] / f"{arquivo_id}.pdf").replace("\\", "/")
