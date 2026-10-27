public final class Kernel {
    public static long kernel(long size) {
        String text = "aé😀z".repeat((int)size);
        long checksum = 0;
        for (int offset = 0; offset < text.length();) {
            int character = text.codePointAt(offset);
            offset += Character.charCount(character);
            if (character == 'a') checksum++;
            else if (character == 'é') checksum += 2;
            else if (character == 0x1f600) checksum += 3;
            else checksum += 4;
        }
        return checksum;
    }
}
