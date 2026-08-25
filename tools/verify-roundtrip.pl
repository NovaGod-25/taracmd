#!/usr/bin/env perl
# Proves the reconstruction is lossless, without needing Python.
#
# Two claims, both checked byte-for-byte against the surviving build:
#
#   1. text-minify(content/*.json) == the original inlined payloads
#      → the pretty-printing in extract-from-build.pl threw nothing away,
#        and key order survived
#   2. substitute(templates/index.html) == the original taracmd.html
#      → the template and the derived counts are right
#
# What this does NOT check is build.py itself running, since it reimplements
# the byte path in Perl. json.dumps(json.load(x)) preserves dict order in
# Python 3.7+, so claim 1 carries over to build.py's own minification.
#
# usage: perl tools/verify-roundtrip.pl path/to/taracmd.html
use strict;
use warnings;
use utf8;

binmode(STDOUT, ':encoding(UTF-8)');

my $src = shift or die "usage: $0 <original taracmd.html>\n";

# Same map, same order as build.py.
my @MAP = (
    [SUBJECTS => 'subjects.json',    '__SUBJECTS__'],
    [PYQ      => 'pyq-papers.json',  '__PYQ__'],
    [TOPPERS  => 'toppers.json',     '__TOPPERS__'],
    [KEYS     => 'answer-keys.json', '__KEYS__'],
    [QUIZ     => 'quiz.json',        '__QUIZ__'],
);

# build.py's SAT_BY, and today.
my %SAT_BY = (prelims => [5, 31], mains => [9, 1]);
my @now = localtime; my ($Y, $M, $D) = ($now[5] + 1900, $now[4] + 1, $now[3]);

sub slurp {
    my ($p) = @_;
    open(my $h, '<:encoding(UTF-8)', $p) or die "cannot read $p: $!\n";
    local $/; my $t = <$h>; close $h; return $t;
}

# Strip whitespace that sits outside string literals. Pure text transform, so
# key order and number spelling are untouched.
sub minify {
    my ($s) = @_;
    my @c = split //, $s;
    my ($out, $in_str, $esc) = ('', 0, 0);
    for my $ch (@c) {
        if ($in_str) {
            $out .= $ch;
            if    ($esc)        { $esc = 0 }
            elsif ($ch eq "\\") { $esc = 1 }
            elsif ($ch eq '"')  { $in_str = 0 }
            next;
        }
        if ($ch eq '"') { $in_str = 1; $out .= $ch; next }
        next if $ch =~ /[\s]/;
        $out .= $ch;
    }
    return $out;
}

# The one place the verifier has to know about content rather than bytes:
# hold back exam years whose exam has not been sat. Operates on minified text.
sub hold_back {
    my ($json) = @_;
    for my $kind (sort keys %SAT_BY) {
        my ($cm, $cd) = @{ $SAT_BY{$kind} };
        # find "kind":[ ... ] and walk its year objects
        next unless $json =~ /"\Q$kind\E":\[/;
        my $start = $+[0];               # just past the [
        my $depth = 1; my $i = $start;
        while ($i < length($json) and $depth > 0) {
            my $ch = substr($json, $i, 1);
            $depth++ if $ch eq '[' or $ch eq '{';
            $depth-- if $ch eq ']' or $ch eq '}';
            $i++;
        }
        my $body = substr($json, $start, $i - 1 - $start);

        # split the array into top-level {...} elements
        my @el; my $d = 0; my $s = 0;
        for my $j (0 .. length($body) - 1) {
            my $ch = substr($body, $j, 1);
            $d++ if $ch eq '{';
            if ($ch eq '}') { $d--; if ($d == 0) { push @el, [$s, $j] } }
            $s = $j + 1 if $d == 0 and $ch eq ',';
        }
        my @keep;
        for my $e (@el) {
            my $txt = substr($body, $e->[0], $e->[1] - $e->[0] + 1);
            my ($yr) = $txt =~ /"year":(\d+)/;
            my $sat = ($yr < $Y)
                   || ($yr == $Y && ($M > $cm || ($M == $cm && $D >= $cd)));
            push @keep, $txt if $sat;
        }
        my $new = join(',', @keep);
        substr($json, $start, $i - 1 - $start) = $new;
    }
    return $json;
}

# ------------------------------------------------------------------- claim 1

my $orig = slurp($src);
my %payload;
for my $line (split /\n/, $orig) {
    next unless $line =~ /^const ([A-Z]+) = (.+);$/;
    $payload{$1} = $2;
}

my $bad = 0;
for my $row (@MAP) {
    my ($name, $file, $token) = @$row;
    my $mine = minify(slurp("content/$file"));
    $mine = hold_back($mine) if $name eq 'PYQ';

    my $want = $payload{$name} // '';
    if ($mine eq $want) {
        printf "  ok    %-16s %8d bytes identical\n", $name, length($mine);
    } else {
        $bad++;
        printf "  FAIL  %-16s mine %d bytes, build %d bytes\n",
            $name, length($mine), length($want);
        # first divergence, with a little context
        my $k = 0; $k++ while $k < length($mine) && $k < length($want)
                            && substr($mine, $k, 1) eq substr($want, $k, 1);
        printf "        diverges at char %d\n          mine: …%s…\n         build: …%s…\n",
            $k, substr($mine, $k - 40 > 0 ? $k - 40 : 0, 90),
                substr($want, $k - 40 > 0 ? $k - 40 : 0, 90);
    }
}

# ------------------------------------------------------------------- claim 2

my $tpl = slurp('templates/index.html');
$tpl =~ s/^<!--\/?PWA-->\n//gm;          # build.py's keep_pwa(), the web variant

my %val = map { $_->[2] => minify(slurp("content/" . $_->[1])) } @MAP;
$val{'__PYQ__'} = hold_back($val{'__PYQ__'});

# derived counts, formatted the way build.py formats them. Decoding is fine
# here — these are counts, so key order does not come into it.
my ($nt, $ns) = (0, 0);
{
    require JSON::PP;
    my $subjects = JSON::PP->new->decode(slurp('content/subjects.json'));
    for my $s (@$subjects) {
        for my $t (@{ $s->{topics} }) {
            $nt++;
            $ns += scalar @{ $t->{subtopics} };
        }
    }
}
sub commas { my $n = reverse shift; $n =~ s/(\d{3})(?=\d)/$1,/g; return scalar reverse $n }
$val{'__N_TOPICS__'}    = commas($nt);
$val{'__N_SUBTOPICS__'} = commas($ns);

print "\n  derived: __N_TOPICS__=$val{'__N_TOPICS__'} __N_SUBTOPICS__=$val{'__N_SUBTOPICS__'}\n\n";

$tpl =~ s/(__[A-Z0-9_]+__)/exists $val{$1} ? $val{$1} : $1/ge;

if (my @left = $tpl =~ /(__[A-Z0-9_]+__)/g) {
    print "  FAIL  unsubstituted: @left\n"; $bad++;
}

if ($tpl eq $orig) {
    printf "  ok    rebuilt page identical to the surviving build (%d bytes)\n", length($tpl);

    # --emit writes the three targets from what was just verified, so the repo
    # has working outputs before Python is installed. `python3 build.py` is the
    # real builder and supersedes this; this is a stopgap, not a second path.
    if (grep { $_ eq '--emit' } @ARGV) {
        my $web = $tpl;

        my $droid = slurp('templates/index.html');
        $droid =~ s/^<!--PWA-->\n.*?^<!--\/PWA-->\n//gms;   # strip_pwa()
        $droid =~ s/^<!--\/?PWA-->\n//gm;
        $droid =~ s/(__[A-Z0-9_]+__)/exists $val{$1} ? $val{$1} : $1/ge;

        my ($style) = $droid =~ /(<style>.*?<\/style>)/s;
        my ($body)  = $droid =~ /<body>\n?(.*?)\n?<\/body>/s;
        my $frag = "$style\n$body\n";

        my %out = (
            'web/taracmd.html'                        => $web,
            'web/artifact.html'                       => $frag,
            'android/app/src/main/assets/index.html'  => $droid,
        );
        print "\n";
        for my $p (sort keys %out) {
            my @parts = split m{/}, $p; pop @parts;
            my $dir = '';
            for my $d (@parts) { $dir .= $d; mkdir $dir unless -d $dir; $dir .= '/' }
            open(my $h, '>:encoding(UTF-8)', $p) or die "cannot write $p: $!\n";
            print $h $out{$p}; close $h;
            printf "  emit  %-40s %8d bytes\n", $p, -s $p;
        }
    }
} else {
    $bad++;
    printf "  FAIL  rebuilt %d bytes, original %d bytes\n", length($tpl), length($orig);
    my $k = 0; $k++ while $k < length($tpl) && $k < length($orig)
                        && substr($tpl, $k, 1) eq substr($orig, $k, 1);
    printf "        diverges at char %d\n          mine: …%s…\n      original: …%s…\n",
        $k, substr($tpl, $k - 60 > 0 ? $k - 60 : 0, 130),
            substr($orig, $k - 60 > 0 ? $k - 60 : 0, 130);
}

print $bad ? "\n$bad check(s) failed\n" : "\nall checks passed\n";
exit($bad ? 1 : 0);
