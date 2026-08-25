#!/usr/bin/env perl
# Rasterise the launcher icon for API 24–25.
#
# The adaptive icon in mipmap-anydpi-v26 covers API 26+. Below that Android
# needs real bitmaps, and minSdk here is 24 — without these, two API levels
# get a blank or system-default launcher icon.
#
# Draws the same mark the web app uses: a rounded square in the brand indigo
# with a "U" cut out of it. Supersampled 4x for smooth edges.
#
# usage: perl tools/make-icons.pl
use strict;
use warnings;
use Compress::Zlib qw(compress);

# density → px, the standard launcher sizes
my %SIZES = (
    'mipmap-mdpi'    => 48,
    'mipmap-hdpi'    => 72,
    'mipmap-xhdpi'   => 96,
    'mipmap-xxhdpi'  => 144,
    'mipmap-xxxhdpi' => 192,
);

my @BG = (0x2E, 0x3D, 0x97);      # --accent
my @FG = (0xFF, 0xFF, 0xFF);

my $SS = 4;                       # supersampling factor

# Geometry on a 0..1 square, matching the SVG's rx=22/100 corner and the
# proportions of the Georgia "U".
my $RADIUS = 0.22;
my $BAR_W  = 0.115;               # stroke width of the U
my $U_L     = 0.315;              # left edge of the U
my $U_R     = 0.685;              # right edge
my $U_TOP   = 0.285;              # top of the uprights
my $U_BOT   = 0.665;              # where the bowl's outer edge sits

sub in_round_rect {
    my ($x, $y, $r) = @_;
    return 0 if $x < 0 || $x > 1 || $y < 0 || $y > 1;
    # distance into the nearest corner
    my $dx = $x < $r ? $r - $x : ($x > 1 - $r ? $x - (1 - $r) : 0);
    my $dy = $y < $r ? $r - $y : ($y > 1 - $r ? $y - (1 - $r) : 0);
    return 1 if $dx == 0 || $dy == 0;
    return ($dx * $dx + $dy * $dy) <= $r * $r ? 1 : 0;
}

sub in_u {
    my ($x, $y) = @_;
    my $cx = ($U_L + $U_R) / 2;
    my $bowl_r = ($U_R - $U_L) / 2;              # outer radius of the bowl
    my $inner_r = $bowl_r - $BAR_W;

    # the two uprights, above where the bowl starts
    my $bowl_top = $U_BOT - $bowl_r;
    if ($y >= $U_TOP && $y <= $bowl_top) {
        return 1 if $x >= $U_L && $x <= $U_L + $BAR_W;
        return 1 if $x >= $U_R - $BAR_W && $x <= $U_R;
        return 0;
    }

    # the bowl: an annulus, lower half only
    if ($y > $bowl_top && $y <= $U_BOT) {
        my $dx = $x - $cx;
        my $dy = $y - $bowl_top;
        my $d = sqrt($dx * $dx + $dy * $dy);
        return ($d <= $bowl_r && $d >= $inner_r) ? 1 : 0;
    }
    return 0;
}

sub crc32_of {
    my ($buf) = @_;
    our @T;
    unless (@T) {
        for my $n (0 .. 255) {
            my $c = $n;
            for (1 .. 8) { $c = ($c & 1) ? (0xEDB88320 ^ ($c >> 1)) : ($c >> 1) }
            $T[$n] = $c;
        }
    }
    my $c = 0xFFFFFFFF;
    for my $b (unpack 'C*', $buf) { $c = $T[($c ^ $b) & 0xFF] ^ ($c >> 8) }
    return $c ^ 0xFFFFFFFF;
}

sub chunk {
    my ($type, $data) = @_;
    return pack('N', length $data) . $type . $data
         . pack('N', crc32_of($type . $data));
}

sub write_png {
    my ($path, $n, $round) = @_;

    my $raw = '';
    for my $py (0 .. $n - 1) {
        $raw .= "\0";                     # filter: none
        for my $px (0 .. $n - 1) {
            my ($hit_bg, $hit_fg) = (0, 0);
            for my $sy (0 .. $SS - 1) {
                for my $sx (0 .. $SS - 1) {
                    my $x = ($px + ($sx + 0.5) / $SS) / $n;
                    my $y = ($py + ($sy + 0.5) / $SS) / $n;
                    my $bg = $round
                        ? ((($x - .5) ** 2 + ($y - .5) ** 2) <= .25 ? 1 : 0)
                        : in_round_rect($x, $y, $RADIUS);
                    next unless $bg;
                    $hit_bg++;
                    $hit_fg++ if in_u($x, $y);
                }
            }
            my $tot = $SS * $SS;
            my $a = int(255 * $hit_bg / $tot + .5);
            my $f = $hit_bg ? $hit_fg / $hit_bg : 0;
            my @c = map { int($BG[$_] + ($FG[$_] - $BG[$_]) * $f + .5) } 0 .. 2;
            $raw .= pack('C4', @c, $a);
        }
    }

    my $ihdr = pack('NNCCCCC', $n, $n, 8, 6, 0, 0, 0);   # 8-bit RGBA
    my $png = "\x89PNG\r\n\x1a\n"
            . chunk('IHDR', $ihdr)
            . chunk('IDAT', compress($raw))
            . chunk('IEND', '');

    open(my $fh, '>:raw', $path) or die "cannot write $path: $!\n";
    print $fh $png;
    close $fh;
    return length $png;
}

my $base = 'android/app/src/main/res';
die "run me from the repo root\n" unless -d $base;

for my $dir (sort keys %SIZES) {
    my $n = $SIZES{$dir};
    mkdir "$base/$dir" unless -d "$base/$dir";
    my $a = write_png("$base/$dir/ic_launcher.png", $n, 0);
    my $b = write_png("$base/$dir/ic_launcher_round.png", $n, 1);
    printf "  %-16s %3dpx  ic_launcher.png %5d B   ic_launcher_round.png %5d B\n",
        $dir, $n, $a, $b;
}
