#!/usr/bin/env perl
# One-shot recovery tool.
#
# Reconstructs content/*.json and templates/index.html from a built taracmd.html.
# Only needed because the project tree was lost and the built page was all that
# survived. It re-indents the inlined JSON by walking the text rather than
# parsing it, so key order is preserved byte-for-byte under minification —
# which is what lets `python3 build.py` reproduce the original page exactly.
#
# usage: perl tools/extract-from-build.pl path/to/taracmd.html
use strict;
use warnings;
use utf8;

binmode(STDOUT, ':encoding(UTF-8)');

my $src = shift or die "usage: $0 <built taracmd.html>\n";

open(my $fh, '<:encoding(UTF-8)', $src) or die "cannot read $src: $!\n";
my @lines = <$fh>;
close $fh;

# const NAME = <json>;  →  content file, template token
my %MAP = (
    SUBJECTS => ['subjects.json',    '__SUBJECTS__'],
    PYQ      => ['pyq-papers.json',  '__PYQ__'],
    TOPPERS  => ['toppers.json',     '__TOPPERS__'],
    KEYS     => ['answer-keys.json', '__KEYS__'],
    QUIZ     => ['quiz.json',        '__QUIZ__'],
);

# Add whitespace outside string literals only. No decode step, so object key
# order and number formatting come through untouched.
sub reindent {
    my ($s) = @_;
    my @c = split //, $s;
    my ($out, $ind, $in_str, $esc) = ('', 0, 0, 0);

    for my $i (0 .. $#c) {
        my $ch = $c[$i];

        if ($in_str) {
            $out .= $ch;
            if    ($esc)          { $esc = 0 }
            elsif ($ch eq "\\")   { $esc = 1 }
            elsif ($ch eq '"')    { $in_str = 0 }
            next;
        }

        if ($ch eq '"') { $in_str = 1; $out .= $ch; next }

        if ($ch eq '{' or $ch eq '[') {
            my $close = $ch eq '{' ? '}' : ']';
            # {} and [] stay on one line
            if ($i < $#c and $c[$i + 1] eq $close) { $out .= $ch; next }
            $ind++;
            $out .= $ch . "\n" . ('  ' x $ind);
            next;
        }

        if ($ch eq '}' or $ch eq ']') {
            if ($out =~ /[\{\[]$/) { $out .= $ch; next }   # closing an empty one
            $ind--;
            $out .= "\n" . ('  ' x $ind) . $ch;
            next;
        }

        if ($ch eq ',') { $out .= ",\n" . ('  ' x $ind); next }
        if ($ch eq ':') { $out .= ': '; next }

        $out .= $ch;
    }
    return $out;
}

my $found = 0;

for my $li (0 .. $#lines) {
    my $line = $lines[$li];
    next unless $line =~ /^const ([A-Z]+) = (.+);\s*$/;
    my ($name, $json) = ($1, $2);
    next unless exists $MAP{$name};

    my ($file, $token) = @{ $MAP{$name} };

    open(my $out, '>:encoding(UTF-8)', "content/$file")
        or die "cannot write content/$file: $!\n";
    print $out reindent($json), "\n";
    close $out;

    printf "content/%-18s %8d bytes in, %8d bytes out\n",
        $file, length($json), -s "content/$file";

    $lines[$li] = "const $name = $token;\n";
    $found++;
}

die "found $found of 5 data blocks — is that a TaraCmd build?\n" unless $found == 5;

# The two derived counts in the search placeholder.
my $n = 0;
for my $li (0 .. $#lines) {
    if ($lines[$li] =~ s/Search [\d,]+ topics and [\d,]+ subtopics/Search __N_TOPICS__ topics and __N_SUBTOPICS__ subtopics/) {
        $n++;
    }
}
warn "note: search placeholder not tokenised\n" unless $n;

open(my $tpl, '>:encoding(UTF-8)', 'templates/index.html')
    or die "cannot write templates/index.html: $!\n";
print $tpl @lines;
close $tpl;

printf "templates/index.html  %8d bytes, %d tokens\n", -s 'templates/index.html', $found + 2 * $n;
