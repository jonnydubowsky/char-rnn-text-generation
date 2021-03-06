from argparse import ArgumentParser
import os
import random
import string
import sys
import numpy as np

###
# file system
###


def make_dirs(path, empty=False):
    """
    create dir in path and clear dir if required
    """
    dir_path = os.path.dirname(path)
    os.makedirs(dir_path, exist_ok=True)

    if empty:
        files = [os.path.join(dir_path, item) for item in os.listdir(dir_path)]
        for item in files:
            if os.path.isfile(item):
                os.remove(item)

    return dir_path


def path_join(*paths, empty=False):
    """
    join paths and create dir
    """
    path = os.path.abspath(os.path.join(*paths))
    make_dirs(os.path.dirname(path), empty)
    return path


###
# data processing
###

def create_dictionary():
    """
    create char2id, id2char and vocab_size
    from printable ascii characters.
    """
    chars = sorted(ch for ch in string.printable if ch not in ("\x0b", "\x0c", "\r"))
    char2id = dict((ch, i + 1) for i, ch in enumerate(chars))
    char2id.update({"": 0})
    id2char = dict((char2id[ch], ch) for ch in char2id)
    vocab_size = len(char2id)
    return char2id, id2char, vocab_size

CHAR2ID, ID2CHAR, VOCAB_SIZE = create_dictionary()


def encode_text(text, char2id=CHAR2ID):
    """
    encode text to array of integers with CHAR2ID
    """
    return np.fromiter((char2id.get(ch, 0) for ch in text), int)


def decode_text(int_array, id2char=ID2CHAR):
    """
    decode array of integers to text with ID2CHAR
    """
    return "".join((id2char[ch] for ch in int_array))


def one_hot_encode(indices, num_classes):
    """
    one-hot encoding
    """
    return np.eye(num_classes)[indices]


def batch_generator(sequence, batch_size=64, seq_len=64, one_hot_features=False, one_hot_labels=False):
    """
    batch generator for sequence
    ensures that batches generated are continuous along axis 1
    so that hidden states can be kept across batches and epochs
    """
    # calculate effective length of text to use
    num_batches = (len(sequence) - 1) // (batch_size * seq_len)
    if num_batches == 0:
        raise ValueError("No batches created. Use smaller batch size or sequence length.")
    print("number of batches: {}".format(num_batches))
    rounded_len = num_batches * batch_size * seq_len
    print("effective text length:{}".format(rounded_len))

    x = np.reshape(sequence[: rounded_len], [batch_size, num_batches * seq_len])
    if one_hot_features:
        x = one_hot_encode(x, VOCAB_SIZE)
    print("x shape: {}".format(x.shape))

    y = np.reshape(sequence[1: rounded_len + 1], [batch_size, num_batches * seq_len])
    if one_hot_labels:
        y = one_hot_encode(y, VOCAB_SIZE)
    print("y shape: {}".format(y.shape))

    epoch = 0
    while True:
        # roll so that no need to reset rnn states over epochs
        x_epoch = np.split(np.roll(x, -epoch, axis=0), num_batches, axis=1)
        y_epoch = np.split(np.roll(y, -epoch, axis=0), num_batches, axis=1)
        for batch in range(num_batches):
            yield x_epoch[batch], y_epoch[batch]
        epoch += 1

# NOTE: there is no rolling in this generator, so RNN states must be
# reset after each Epoch
def io_batch_generator(text_path, max_bytes_in_ram=1000000, batch_size=64, seq_len=64, one_hot_features=False, one_hot_labels=False):
    """
    batch generator for sequence
    ensures that batches generated are continuous along axis 1
    so that hidden states can be kept across batches and epochs
    """

    total_bytes = os.path.getsize(text_path)
    effective_file_end = total_bytes - total_bytes % max_bytes_in_ram
    
    print('total_bytes: {}'.format(total_bytes))
    print('max_bytes_in_ram: {}'.format(max_bytes_in_ram))
    print('effective_file_end: {}'.format(effective_file_end))

    with open(text_path, 'r') as file:
        epoch = 0
        while True:

            # once we are back at the beginning of the file we have 
            # entered a new epoch. Epoch is also initialized to zero so
            # that it will be set to one here at the beginning.
            if file.tell() == 0: 
                epoch += 1
                print('debug: now in epoch {}'.format(epoch))

            # load max_bytes_in_ram into ram
            io_batch = file.read(max_bytes_in_ram)
            print('debug: new io_batch of {} bytes'.format(max_bytes_in_ram))
            
            # if we are within max_bytes_in_ram of the effecitive
            # end of the file, set the file read playhead back to
            # the beginning, which will increase the epoch next loop
            if file.tell() + max_bytes_in_ram > effective_file_end:
                file.seek(0)

            # print('debug: encoding {} bytes of text from io_batch'.format(len(io_batch)))
            # encode this batch of text
            encoded = encode_text(io_batch)

            # the number of data batches for this io batch of bytes in RAM
            num_batches = (len(encoded) - 1) // (batch_size * seq_len)
            
            if num_batches == 0:
                raise ValueError("No batches created. Use smaller batch_size or seq_leng or larger value for max_bytes_in_ram.")
            
            # print("debug: number of batches in io_batch: {}".format(num_batches))
            
            rounded_len = num_batches * batch_size * seq_len
            # print("debug: effective text length in io_batch: {}".format(rounded_len))

            x = np.reshape(encoded[: rounded_len], [batch_size, num_batches * seq_len])
            if one_hot_features:
                x = one_hot_encode(x, VOCAB_SIZE)
            # print("debug: x shape: {}".format(x.shape))

            y = np.reshape(encoded[1: rounded_len + 1], [batch_size, num_batches * seq_len])
            if one_hot_labels:
                y = one_hot_encode(y, VOCAB_SIZE)
            # print("debug: y shape: {}".format(y.shape))

            x_batches = np.split(x, num_batches, axis=1)
            y_batches = np.split(y, num_batches, axis=1)

            for batch in range(num_batches):
                yield x_batches[batch], y_batches[batch], epoch
            
            # free the mem
            del x
            del y
            del x_batches
            del y_batches
            del encoded

###
# text generation
###

def generate_seed(text, seq_lens=(2, 4, 8, 16, 32)):
    """
    select subsequence randomly from input text
    """
    # randomly choose sequence length
    seq_len = random.choice(seq_lens)
    # randomly choose start index
    start_index = random.randint(0, len(text) - seq_len - 1)
    seed = text[start_index: start_index + seq_len]
    return seed


def sample_from_probs(probs, top_n=10):
    """
    truncated weighted random choice.
    """
    # need 64 floating point precision
    probs = np.array(probs, dtype=np.float64)
    # set probabilities after top_n to 0
    probs[np.argsort(probs)[:-top_n]] = 0
    # renormalise probabilities
    probs /= np.sum(probs)
    sampled_index = np.random.choice(len(probs), p=probs)
    return sampled_index


###
# main
###

def main(framework, train_main, generate_main):
    arg_parser = ArgumentParser(
        description="{} character embeddings LSTM text generation model.".format(framework))
    subparsers = arg_parser.add_subparsers(title="subcommands")

    # train args
    train_parser = subparsers.add_parser("train", help="train model on text file")
    train_parser.add_argument("--checkpoint-path", required=True,
                              help="path to save or load model checkpoints (required)")
    train_parser.add_argument("--text-path", required=True,
                              help="path of text file for training (required)")
    train_parser.add_argument("--restore", nargs="?", default=False, const=True,
                              help="whether to restore from checkpoint_path "
                                   "or from another path if specified")
    train_parser.add_argument("--seq-len", type=int, default=64,
                              help="sequence length of inputs and outputs (default: %(default)s)")
    train_parser.add_argument("--embedding-size", type=int, default=32,
                              help="character embedding size (default: %(default)s)")
    train_parser.add_argument("--rnn-size", type=int, default=128,
                              help="size of rnn cell (default: %(default)s)")
    train_parser.add_argument("--num-layers", type=int, default=2,
                              help="number of rnn layers (default: %(default)s)")
    train_parser.add_argument("--drop-rate", type=float, default=0.,
                              help="dropout rate for rnn layers (default: %(default)s)")
    train_parser.add_argument("--learning-rate", type=float, default=0.001,
                              help="learning rate (default: %(default)s)")
    train_parser.add_argument("--clip-norm", type=float, default=5.,
                              help="max norm to clip gradient (default: %(default)s)")
    train_parser.add_argument("--batch-size", type=int, default=64,
                              help="training batch size (default: %(default)s)")
    train_parser.add_argument("--num-epochs", type=int, default=32,
                              help="number of epochs for training (default: %(default)s)")
    train_parser.add_argument("--log-path", default=os.path.join(os.path.dirname(__file__), "main.log"),
                              help="path of log file (default: %(default)s)")
    train_parser.set_defaults(main=train_main)

    # generate args
    generate_parser = subparsers.add_parser("generate", help="generate text from trained model")
    generate_parser.add_argument("--checkpoint-path", required=True,
                                 help="path to load model checkpoints (required)")
    group = generate_parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--text-path", help="path of text file to generate seed")
    group.add_argument("--seed", default=None, help="seed character sequence")
    generate_parser.add_argument("--length", type=int, default=1024,
                                 help="length of character sequence to generate (default: %(default)s)")
    generate_parser.add_argument("--top-n", type=int, default=3,
                                 help="number of top choices to sample (default: %(default)s)")
    generate_parser.add_argument("--log-path", default=os.path.join(os.path.dirname(__file__), "main.log"),
                                 help="path of log file (default: %(default)s)")
    generate_parser.set_defaults(main=generate_main)

    args = arg_parser.parse_args()

    args.main(args)
    