# Maintainer: lucial <lucial@example.com>
pkgname=imagefinish
pkgver=1.1.0
pkgrel=1
pkgdesc="A PyQt6 image editor inspired by Photoshop"
arch=('any')
url="https://github.com/7Lucia7Lokidottir7/Linux-Photoshop"
license=('MIT')
depends=('python' 'python-pyqt6')
optdepends=('python-numpy: faster pixel operations')
source=("git+https://github.com/7Lucia7Lokidottir7/Linux-Photoshop.git")
sha256sums=('SKIP')

pkgver() {
    cd "Linux-Photoshop"
    git describe --tags --long 2>/dev/null | sed 's/\([^-]*-g\)/r\1/;s/-/./g' \
        || printf "1.1.0.r%s.%s" "$(git rev-list --count HEAD)" "$(git rev-parse --short HEAD)"
}

package() {
    cd "Linux-Photoshop"

    # App files
    install -dm755 "${pkgdir}/usr/share/${pkgname}"
    cp -r core locales tools ui utils brushes fonts patterns shapes \
        "${pkgdir}/usr/share/${pkgname}/"
    install -Dm644 main.py "${pkgdir}/usr/share/${pkgname}/main.py"

    # Icon
    install -Dm644 icon.png "${pkgdir}/usr/share/pixmaps/${pkgname}.png"

    # Launcher script
    install -dm755 "${pkgdir}/usr/bin"
    cat > "${pkgdir}/usr/bin/${pkgname}" <<'EOF'
#!/bin/bash
cd /usr/share/imagefinish
exec python3 main.py "$@"
EOF
    chmod 755 "${pkgdir}/usr/bin/${pkgname}"

    # .desktop entry
    install -Dm644 imagefinish.desktop \
        "${pkgdir}/usr/share/applications/${pkgname}.desktop"
}
